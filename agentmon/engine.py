"""
Pipeline quyết định (đúng sơ đồ yêu cầu):

  [1] Hard Policy (hạn mức cứng TSC→CN→KH, pháp lý Agent, số dư, PCI)  → vi phạm = BLOCK ngay, ML/LLM không ghi đè
  [2] Feature Engineering (hành vi riêng của từng khách + velocity)
  [3] Isolation Forest (điểm bất thường, mỗi domain 1 mô hình)
  [4] LLM Critic (Groq; chỉ được nâng mức, giải thích tiếng Việt)
  [5] Quyết định: ALLOW | KYA (khách xác nhận qua Authenticator) | REVIEW (nhân viên CN duyệt) | BLOCK
  [6] Lưu CSDL + thực hiện (hạch toán số dư) khi được phép
"""
import math
import re
import threading
import time

from agentmon import cards, critic, db, features as F, kya, ml, policy, registry
from services.audit_log import add_log
from utils import store

_eval_lock = threading.RLock()
ACTIVE_ST = ("EXECUTED", "PENDING_KYA", "REVIEW_PENDING")
ORDER = {"ALLOW": 0, "KYA": 1, "REVIEW": 2, "BLOCK": 3}
PUBLIC_MSG = {
    "ALLOW": "Giao dịch được chấp thuận và đã thực hiện.",
    "KYA": "Giao dịch bất thường – cần khách hàng xác minh (KYA) qua ứng dụng Authenticator trước khi thực hiện.",
    "REVIEW": "Giao dịch được giữ lại chờ nhân viên chi nhánh xét duyệt.",
    "BLOCK": "Giao dịch bị chặn.",
}


class BadRequest(Exception):
    pass


def _num(v, name, positive=True):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise BadRequest(f"{name} phải là số.")
    if not math.isfinite(x) or (positive and x <= 0):
        raise BadRequest(f"{name} phải là số dương hợp lệ.")
    return x


def usd_vnd():
    try:
        return float(policy.get_tsc("FX")["global"].get("usd_vnd", 26200))
    except Exception:
        return 26200.0


def normalize(raw: dict, now: float, sim_hour=None) -> dict:
    if not isinstance(raw, dict):
        raise BadRequest("Payload không hợp lệ.")
    domain = str(raw.get("domain", "")).upper()
    kind = str(raw.get("kind", "")).upper()
    a = {"domain": domain, "kind": kind, "ts": now,
         "hour": int(sim_hour) if sim_hour is not None else F.local_hour(now),
         "client_ref": (str(raw.get("request_id"))[:64] if raw.get("request_id") else None)}
    if domain == "FX":
        if kind != "FX_TRADE":
            raise BadRequest("FX chỉ hỗ trợ kind=FX_TRADE.")
        a["pair"] = str(raw.get("pair", "")).upper()[:10]
        a["side"] = str(raw.get("side", "")).upper()
        if a["side"] not in ("BUY", "SELL"):
            raise BadRequest("side phải là BUY hoặc SELL.")
        a["amount_usd"] = _num(raw.get("notional_usd"), "notional_usd")
        a["leverage"] = _num(raw.get("leverage", 1), "leverage")
        if a["leverage"] < 1:
            raise BadRequest("leverage phải ≥ 1.")
        rate = usd_vnd()
        a["amount_vnd"] = a["amount_usd"] * rate
        a["margin_vnd"] = a["amount_vnd"] / a["leverage"]
    elif domain == "PAY":
        if kind not in ("TRANSFER", "ONLINE_PURCHASE", "CARD_PAYMENT"):
            raise BadRequest("kind phải là TRANSFER, ONLINE_PURCHASE hoặc CARD_PAYMENT.")
        a["amount_vnd"] = _num(raw.get("amount_vnd"), "amount_vnd")
        a["margin_vnd"] = None
        if kind == "TRANSFER":
            ben = re.sub(r"\s", "", str(raw.get("beneficiary_account", "")))
            if not ben.isdigit() or not (6 <= len(ben) <= 20):
                raise BadRequest("beneficiary_account phải gồm 6–20 chữ số.")
            a["beneficiary"] = ben
            a["merchant"] = a["country"] = a["mcc"] = None
        else:
            a["card_token"] = str(raw.get("card_token", ""))[:64]
            a["merchant"] = str(raw.get("merchant_id", ""))[:40] or None
            if not a["merchant"]:
                raise BadRequest("Thiếu merchant_id.")
            mcc = str(raw.get("mcc", ""))
            if not re.fullmatch(r"\d{4}", mcc):
                raise BadRequest("mcc phải gồm 4 chữ số.")
            a["mcc"] = mcc
            ctry = str(raw.get("country", "VN")).upper()
            if not re.fullmatch(r"[A-Z]{2}", ctry):
                raise BadRequest("country phải là mã ISO 2 ký tự.")
            a["country"] = ctry
            a["channel_type"] = "CNP" if kind == "ONLINE_PURCHASE" else str(raw.get("channel_type", "POS")).upper()
            if a["channel_type"] not in ("CNP", "POS"):
                raise BadRequest("channel_type phải là CNP hoặc POS.")
            a["three_ds"] = bool(raw.get("three_ds"))
            a["beneficiary"] = None
    else:
        raise BadRequest("domain phải là FX hoặc PAY.")
    return a


def _day_start(now):
    return ((now + F.LOCAL_TZ_OFFSET) // 86400) * 86400 - F.LOCAL_TZ_OFFSET


def _month_start(now):
    t = time.gmtime(now + F.LOCAL_TZ_OFFSET)
    import calendar
    return calendar.timegm((t.tm_year, t.tm_mon, 1, 0, 0, 0)) - F.LOCAL_TZ_OFFSET


def _sum(sql, args):
    r = db.one(sql, args)
    return float(list(r.values())[0] or 0) if r else 0.0


def available_balance(customer_id):
    acc = db.one("SELECT balance_vnd FROM accounts WHERE customer_id=?", (customer_id,))
    bal = float(acc["balance_vnd"]) if acc else 0.0
    res = _sum("SELECT SUM(CASE WHEN domain='FX' THEN amount_vnd/COALESCE(leverage,1) ELSE amount_vnd END) FROM actions "
               "WHERE customer_id=? AND status IN ('PENDING_KYA','REVIEW_PENDING')", (customer_id,))
    return bal, bal - res


def build_ctx(a, agent, customer, eff, now):
    cid = customer["customer_id"]
    dom = a["domain"]
    hist = db.query("SELECT * FROM actions WHERE customer_id=? AND domain=? AND status='EXECUTED' AND ts>? AND ts<=? AND sim!=2 "
                    "ORDER BY ts DESC LIMIT 600", (cid, dom, now - 365 * 86400, now))
    att = db.query("SELECT ts, amount_vnd, decision, status FROM actions WHERE agent_id=? AND ts>? AND ts<=? AND sim!=2 ORDER BY ts DESC LIMIT 400",
                   (agent["agent_id"], now - 86400, now)) if agent else []
    bal, avail = available_balance(cid)
    ds, ms = _day_start(now), _month_start(now)
    st = "('EXECUTED','PENDING_KYA','REVIEW_PENDING') AND sim!=2"
    cum = {}
    if dom == "FX":
        cum["day"] = _sum(f"SELECT SUM(amount_usd) FROM actions WHERE customer_id=? AND domain='FX' AND status IN {st} AND ts>=?", (cid, ds))
    else:
        cum["day_transfer"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind='TRANSFER' AND status IN {st} AND ts>=?", (cid, ds))
        cum["month_transfer"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind='TRANSFER' AND status IN {st} AND ts>=?", (cid, ms))
        cum["day_card"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind IN ('CARD_PAYMENT','ONLINE_PURCHASE') AND status IN {st} AND ts>=?", (cid, ds))
        if a.get("card_id"):
            cum["day_this_card"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE card_id=? AND status IN {st} AND ts>=?", (a["card_id"], ds))
    cum["hour_n"] = _sum("SELECT COUNT(*) FROM actions WHERE agent_id=? AND decision!='BLOCK' AND sim!=2 AND ts>?", (agent["agent_id"], now - 3600)) if agent else 0
    cum["day_n"] = _sum("SELECT COUNT(*) FROM actions WHERE agent_id=? AND decision!='BLOCK' AND sim!=2 AND ts>=?", (agent["agent_id"], ds)) if agent else 0
    trusted = {r["account"] for r in db.query("SELECT account FROM trusted_beneficiaries WHERE customer_id=?", (cid,))}
    onl = db.one("SELECT COUNT(*) n, MAX(ts) m FROM actions WHERE customer_id=? AND status='EXECUTED' AND channel IN ('AGENT','ONLINE') AND sim!=2 AND ts<=?", (cid, now))
    last = db.one("SELECT MAX(ts) m FROM actions WHERE customer_id=? AND status='EXECUTED' AND sim!=2 AND ts<=?", (cid, now))
    fl = db.one("SELECT * FROM flags WHERE customer_id=?", (cid,)) or {}
    ctx = F.Ctx(dom, now, hist, att, avail, eff, trusted, online_exec_any=int(onl["n"] or 0), last_exec_ts=last["m"],
                agent_prior=int(db.one("SELECT COUNT(*) n FROM actions WHERE agent_id=?", (agent["agent_id"],))["n"]) if agent else 0,
                probation_left=int(agent["probation_left"] or 0) if agent else 0, suspicion=float(fl.get("suspicion") or 0),
                watchlist=bool(fl.get("watchlist")), cum=cum)
    ctx.balance_total = bal
    return ctx


def hard_policy(a, agent, customer, eff, ctx, pci_violation):
    """Trả danh sách lý do vi phạm cứng. Rỗng = hợp lệ."""
    R = []
    ks = policy.kill_switch()
    if ks.get("on"):
        R.append(f"TSC đã bật KILL-SWITCH toàn hệ thống: {ks.get('reason') or 'tạm dừng AI Agent'}")
    ok, why = registry.is_usable(agent)
    if not ok:
        R.append(why)
        return R
    if a["domain"] not in agent["domains"]:
        R.append(f"Agent không được đăng ký cho nghiệp vụ {a['domain']}")
    if a["kind"] not in agent["kinds"]:
        R.append(f"Loại giao dịch {a['kind']} không nằm trong đăng ký của Agent")
    if (customer.get("status") or "").upper() != "ACTIVE":
        R.append("Khách hàng không ở trạng thái hoạt động")
    if not customer.get("online"):
        R.append("CIF chưa được chi nhánh bật dịch vụ online")
    if pci_violation:
        R.append("PCI-DSS: payload chứa số thẻ đầy đủ/CVV/PIN – Agent chỉ được dùng token thẻ")
    g = eff["_global"]
    amt = a["amount_usd"] if a["domain"] == "FX" else a["amount_vnd"]
    if ctx.cum.get("hour_n", 0) >= float(eff["per_hour"]):
        R.append(f"Vượt số giao dịch/giờ ({eff['per_hour']:g})")
    if ctx.cum.get("day_n", 0) >= float(eff["per_day"]):
        R.append(f"Vượt số giao dịch/ngày ({eff['per_day']:g})")
    if a["domain"] == "FX":
        if a["pair"] not in policy.FX_PAIRS or a["pair"] not in eff.get("allowed_pairs", []):
            R.append(f"Cặp tiền {a['pair']} không nằm trong danh mục được phép")
        if a["leverage"] > float(eff["max_leverage"]):
            R.append(f"Đòn bẩy {a['leverage']:g}x vượt hạn mức {float(eff['max_leverage']):g}x")
        if a["amount_usd"] > float(eff["per_order_usd"]):
            R.append(f"Giá trị lệnh {a['amount_usd']:,.0f} USD vượt hạn mức/lệnh {float(eff['per_order_usd']):,.0f} USD")
        if ctx.cum.get("day", 0) + a["amount_usd"] > float(eff["daily_usd"]):
            R.append(f"Vượt hạn mức ngày {float(eff['daily_usd']):,.0f} USD (đã dùng {ctx.cum.get('day', 0):,.0f})")
        hf, ht = eff.get("hours_from"), eff.get("hours_to")
        if hf is not None and ht is not None and not (int(hf) <= a["hour"] < int(ht)):
            R.append(f"Ngoài khung giờ Agent được phép giao dịch ({int(hf)}h–{int(ht)}h)")
        need = a["margin_vnd"]
    else:
        need = a["amount_vnd"]
        if a["kind"] == "TRANSFER":
            if a["beneficiary"] in g.get("blocked_accounts", []):
                R.append("Tài khoản thụ hưởng nằm trong danh sách chặn")
            if a["amount_vnd"] > float(eff["transfer_per_txn"]):
                R.append(f"Chuyển tiền {a['amount_vnd']:,.0f} VND vượt hạn mức/lần {float(eff['transfer_per_txn']):,.0f}")
            if ctx.cum["day_transfer"] + a["amount_vnd"] > float(eff["transfer_daily"]):
                R.append(f"Vượt hạn mức chuyển tiền ngày {float(eff['transfer_daily']):,.0f} VND")
            if ctx.cum["month_transfer"] + a["amount_vnd"] > float(eff["transfer_monthly"]):
                R.append(f"Vượt hạn mức chuyển tiền tháng {float(eff['transfer_monthly']):,.0f} VND")
        else:
            card = a.get("card")
            if not card:
                R.append("Token thẻ không hợp lệ hoặc không thuộc khách hàng này")
            else:
                if card["status"] != "ACTIVE":
                    R.append(f"Thẻ {card['network']} …{card['last4']} đang ở trạng thái {card['status']}")
                if cards.expired(card["exp_month"], card["exp_year"], a["ts"]):
                    R.append("Thẻ đã hết hạn")
                if a["channel_type"] == "CNP" and not card["cnp_enabled"]:
                    R.append("Thẻ chưa bật thanh toán online (CNP)")
                if a["country"] != "VN" and not card["intl_enabled"]:
                    R.append("Thẻ chưa bật giao dịch quốc tế")
                if card.get("per_txn_limit") and a["amount_vnd"] > float(card["per_txn_limit"]):
                    R.append(f"Vượt hạn mức/giao dịch của thẻ ({float(card['per_txn_limit']):,.0f})")
                if card.get("daily_limit") and ctx.cum.get("day_this_card", 0) + a["amount_vnd"] > float(card["daily_limit"]):
                    R.append(f"Vượt hạn mức/ngày của thẻ ({float(card['daily_limit']):,.0f})")
            cap = float(eff["online_per_txn"] if a["kind"] == "ONLINE_PURCHASE" else eff["card_per_txn"])
            if a["amount_vnd"] > cap:
                R.append(f"Giá trị {a['amount_vnd']:,.0f} VND vượt hạn mức {('mua sắm online' if a['kind']=='ONLINE_PURCHASE' else 'thẻ')}/lần ({cap:,.0f})")
            if ctx.cum["day_card"] + a["amount_vnd"] > float(eff["card_daily"]):
                R.append(f"Vượt hạn mức thanh toán thẻ/ngày ({float(eff['card_daily']):,.0f} VND)")
            if a["mcc"] in g.get("blocked_mcc", []):
                R.append(f"Ngành hàng bị cấm (MCC {a['mcc']})")
            if a["country"] in g.get("blocked_countries", []):
                R.append(f"Quốc gia bị cấm vận/chặn ({a['country']})")
    if need > ctx.balance:
        R.append(f"Vượt số dư tiền gửi thanh toán khả dụng ({ctx.balance:,.0f} VND, cần {need:,.0f} VND)")
    return R


def _persist(a, agent_id, customer_id, branch_id, source, res, details, sim):
    ts = a["ts"]
    return db.execute(
        "INSERT INTO actions(ts,domain,kind,customer_id,branch_id,agent_id,channel,client_ref,amount_vnd,amount_usd,pair,side,leverage,"
        "beneficiary,merchant,mcc,country,card_id,hour,details,anomaly,behavior,velocity,final_risk,decision,status,hard_reason,"
        "reasons,triggers,reason_public,llm,source,sim) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, a["domain"], a["kind"], customer_id, branch_id, agent_id, "AGENT", a.get("client_ref"), a.get("amount_vnd"),
         a.get("amount_usd"), a.get("pair"), a.get("side"), a.get("leverage"), a.get("beneficiary"), a.get("merchant"),
         a.get("mcc"), a.get("country"), (a.get("card") or {}).get("card_id"), a["hour"], db.jdump(details),
         res.get("anomaly"), res.get("behavior"), res.get("velocity"), res.get("final_risk"), res["decision"], res["status"],
         res.get("hard_reason"), db.jdump(res.get("reasons", [])), db.jdump(res.get("triggers", [])), res["reason_public"],
         db.jdump(res.get("llm")), source, 1 if sim else 0))


def bump_suspicion(customer_id, delta):
    if not customer_id:
        return
    r = db.one("SELECT suspicion FROM flags WHERE customer_id=?", (customer_id,))
    s = min(1.0, max(0.0, (float(r["suspicion"]) if r else 0.0) + delta))
    db.execute("INSERT INTO flags(customer_id,suspicion,watchlist,updated_at) VALUES(?,?,?,?) ON CONFLICT(customer_id) DO UPDATE "
               "SET suspicion=excluded.suspicion, watchlist=excluded.watchlist, updated_at=excluded.updated_at",
               (customer_id, s, 1 if s > 0.7 else 0, store.now()))


def evaluate(raw: dict, agent_id: str, source: str = "AGENT_API", customer_hint: str = "", sim_hour=None,
             sim_ts=None, ip: str = "", use_llm: bool = True) -> dict:
    from app.customer.mock_db import get_demo_customer
    now = float(sim_ts) if sim_ts else store.now()
    pci = cards.find_pan_in(raw)
    safe_raw = cards.redact(raw)
    a = normalize(safe_raw, now, sim_hour)     # chuẩn hóa trên bản đã che PAN
    with _eval_lock:
        agent = registry.get(agent_id)
        if a.get("client_ref") and agent:
            ex = db.one("SELECT id FROM actions WHERE agent_id=? AND client_ref=?", (agent_id, a["client_ref"]))
            if ex:
                return get_action_result(ex["id"], duplicate=True)
        cid = agent["customer_id"] if agent else customer_hint
        customer = get_demo_customer(cid) if cid else None
        customer = customer or {"customer_id": cid or "UNKNOWN", "segment": "STANDARD", "status": "UNKNOWN", "online": False, "branch_id": ""}
        domain_limits = (agent or {}).get("limits", {}).get(a["domain"], {}) if agent else {}
        eff = policy.effective_limits(a["domain"], customer.get("segment", "STANDARD"), cid, domain_limits)
        if a["domain"] == "PAY" and a["kind"] != "TRANSFER" and agent:
            c = db.one("SELECT * FROM cards WHERE token=? AND customer_id=?", (a.get("card_token", ""), cid))
            if c:
                a["card"] = c
                a["card_id"] = c["card_id"]
        ctx = build_ctx(a, agent, customer, eff, now)
        hard = hard_policy(a, agent, customer, eff, ctx, pci)
        details = {k: v for k, v in a.items() if k not in ("card", "card_token", "ts")}
        details["card_last4"] = (a.get("card") or {}).get("last4")
        details["pci_violation"] = pci
        res = {"reasons": [], "triggers": [], "llm": None}
        if hard:
            res.update(decision="BLOCK", status="BLOCKED", hard_reason="; ".join(hard), final_risk=1.0, anomaly=None,
                       behavior=None, velocity=None, reasons=hard, reason_public="Bị chặn: " + hard[0])
            if pci:
                res["triggers"] = [("PCI_VIOLATION", "Agent gửi PAN/CVV – dữ liệu đã được che")]
            if agent:
                bump_suspicion(cid, 0.25 if pci else 0.05)
        else:
            vec = F.feature_vector(a, ctx)
            an = ml.anomaly(a["domain"], vec)
            beh, why_b = F.behavior_score(a, ctx)
            vel, why_v = F.velocity_score(a, ctx)
            raw_final = 0.40 * an + 0.30 * beh + 0.30 * vel
            final = 0.7 * raw_final + 0.3 * max(beh, vel)     # ML đơn độc không được kéo điểm lên – cần tín hiệu hành vi/velocity đồng thuận
            if ctx.watchlist:
                final = min(1.0, final + 0.10)
                why_b.append("Khách hàng đang trong danh sách theo dõi (suspicion cao)")
            trig = F.triggers(a, ctx)
            g = eff["_global"]
            if final >= float(g["block_threshold"]):
                dec = "BLOCK"
            elif final >= float(g["review_threshold"]):
                dec = "REVIEW"
            elif final >= float(g["kya_threshold"]) or trig:
                dec = "KYA"
            else:
                dec = "ALLOW"
            reasons = []
            if an > 0.35:
                reasons.append(f"ML bất thường {an:.2f}")
            reasons += why_b + why_v
            llm = None
            if use_llm and critic.should_call(final, dec, trig):
                summary = {"domain": a["domain"], "kind": a["kind"], "final_risk": round(final, 3), "anomaly": round(an, 3),
                           "behavior": round(beh, 3), "velocity": round(vel, 3), "hour": a["hour"],
                           "ratio": round(F.context_flags(a, ctx)["ratio"], 2), "trigger_codes": [t[0] for t in trig],
                           "amount_bucket": "%.1e" % (a["amount_usd"] if a["domain"] == "FX" else a["amount_vnd"]),
                           "unit": "USD" if a["domain"] == "FX" else "VND", "kind_detail": a.get("kind"),
                           "country": a.get("country"), "mcc": a.get("mcc"), "leverage": a.get("leverage"),
                           "initial_decision": dec}
                llm = critic.critique(summary)
                rec = llm["recommendation"]
                if ORDER[rec] > ORDER[dec] and rec in ("KYA", "REVIEW"):
                    reasons.append(f"LLM nâng mức {dec}→{rec}")
                    dec = rec
            if dec == "KYA":
                if not kya.enrolled(cid):
                    dec = "BLOCK"
                    reasons.append("Cần KYA nhưng khách hàng CHƯA đăng ký Authenticator (fail-closed)")
                elif _sum("SELECT COUNT(*) FROM kya WHERE customer_id=? AND status='PENDING'", (cid,)) >= int(g["max_pending_kya"]):
                    dec = "BLOCK"
                    reasons.append("Quá nhiều yêu cầu KYA đang chờ (chống dội thông báo xác minh)")
            status = {"ALLOW": "PENDING_EXEC", "KYA": "PENDING_KYA", "REVIEW": "REVIEW_PENDING", "BLOCK": "BLOCKED"}[dec]
            pub = PUBLIC_MSG[dec]
            if dec == "BLOCK":
                pub = "Giao dịch bị chặn do mức rủi ro quá cao." if not reasons or "Authenticator" not in reasons[-1] else "Bị chặn: " + reasons[-1]
            res.update(decision=dec, status=status, final_risk=round(final, 4), anomaly=round(an, 4), behavior=round(beh, 4),
                       velocity=round(vel, 4), reasons=reasons, triggers=[list(t) for t in trig], llm=llm, reason_public=pub)
            if dec in ("KYA", "REVIEW", "BLOCK"):
                bump_suspicion(cid, {"KYA": 0.05, "REVIEW": 0.15, "BLOCK": 0.30}[dec])
        aid = _persist(a, agent_id, cid if cid else None, customer.get("branch_id"), source, res, details, sim_ts is not None or sim_hour is not None)
        out = {"action_id": aid}
        if res["decision"] == "KYA":
            ttl = int(eff["_global"]["kya_ttl_seconds"])
            kid = kya.create_challenge(aid, cid, ttl)
            db.execute("UPDATE actions SET kya_id=? WHERE id=?", (kid, aid))
        if res["decision"] == "ALLOW":
            if agent and agent["probation_left"]:
                db.execute("UPDATE agents SET probation_left=MAX(probation_left-1,0) WHERE agent_id=?", (agent_id,))
            execute_action(aid, via="AUTO")
        elif res["decision"] == "KYA" and agent and agent["probation_left"]:
            db.execute("UPDATE agents SET probation_left=MAX(probation_left-1,0) WHERE agent_id=?", (agent_id,))
    add_log("agent_action", user_id=agent_id, customer_id=cid or "", branch_id=customer.get("branch_id") or "",
            level="warn" if res["decision"] in ("BLOCK", "REVIEW") else "info", ip=ip,
            detail={"action_id": aid, "domain": a["domain"], "kind": a["kind"], "decision": res["decision"],
                    "risk": res.get("final_risk"), "source": source})
    return get_action_result(aid)


def get_action_result(aid, duplicate=False):
    r = db.one("SELECT * FROM actions WHERE id=?", (aid,))
    d = dict(r)
    for k in ("details", "reasons", "triggers", "llm"):
        d[k] = db.jload(d.get(k), [] if k in ("reasons", "triggers") else None)
    d["duplicate"] = duplicate
    d["action_id"] = aid
    if d.get("kya_id"):
        k = db.one("SELECT status, expires_at FROM kya WHERE id=?", (d["kya_id"],))
        d["kya"] = {"id": d["kya_id"], "status": k["status"], "expires_in": max(0, int(k["expires_at"] - store.now()))}
    return d


def execute_action(aid, via="AUTO"):
    """Hạch toán số dư. Kiểm tra lại số dư/Agent/kill-switch tại thời điểm thực hiện (chống TOCTOU)."""
    with _eval_lock, db.tx() as c:
        r = c.execute("SELECT * FROM actions WHERE id=?", (aid,)).fetchone()
        if not r:
            return {"status": "NOT_FOUND"}
        r = dict(r)
        if r["status"] not in ("PENDING_EXEC", "PENDING_KYA", "REVIEW_PENDING"):
            return {"status": r["status"]}
        need = (r["amount_vnd"] / (r["leverage"] or 1)) if r["domain"] == "FX" else r["amount_vnd"]
        acc = c.execute("SELECT balance_vnd FROM accounts WHERE customer_id=?", (r["customer_id"],)).fetchone()
        bal = float(acc["balance_vnd"]) if acc else 0.0
        ag = c.execute("SELECT status FROM agents WHERE agent_id=?", (r["agent_id"],)).fetchone()
        fail = None
        if policy.kill_switch().get("on"):
            fail = "TSC đang bật kill-switch"
        elif not ag or ag["status"] != "ACTIVE":
            fail = "Agent không còn ở trạng thái hoạt động"
        elif need > bal:
            fail = "Số dư không đủ tại thời điểm thực hiện"
        if fail:
            c.execute("UPDATE actions SET status='FAILED', reason_public=? WHERE id=?", ("Không thực hiện được: " + fail, aid))
            return {"status": "FAILED", "reason": fail}
        c.execute("UPDATE accounts SET balance_vnd=balance_vnd-? WHERE customer_id=?", (need, r["customer_id"]))
        c.execute("UPDATE actions SET status='EXECUTED', executed_at=?, reason_public=? WHERE id=?",
                  (store.now(), "Giao dịch đã thực hiện" + (f" (xác minh: {via})" if via != "AUTO" else ""), aid))
    if via.startswith("KYA"):
        bump_suspicion(r["customer_id"], -0.05)
    add_log("agent_action_executed", user_id=r["agent_id"], customer_id=r["customer_id"] or "", detail={"action_id": aid, "via": via})
    return {"status": "EXECUTED"}


def on_customer_denied(aid):
    r = db.one("SELECT agent_id, customer_id FROM actions WHERE id=?", (aid,))
    if not r:
        return
    db.execute("UPDATE agents SET denied_count=denied_count+1 WHERE agent_id=?", (r["agent_id"],))
    bump_suspicion(r["customer_id"], 0.20)
    ag = registry.get(r["agent_id"])
    if ag and ag["denied_count"] >= kya.DENY_LIMIT and ag["status"] == "ACTIVE":
        registry.set_status(r["agent_id"], "SUSPENDED", f"Tự động: khách từ chối KYA {ag['denied_count']} lần", "system")
        add_log("agent_auto_suspended", user_id=r["agent_id"], customer_id=r["customer_id"], level="critical",
                detail={"denied": ag["denied_count"]})


def review_action(aid, reviewer, approve: bool, note=""):
    r = db.one("SELECT * FROM actions WHERE id=?", (aid,))
    if not r or r["status"] != "REVIEW_PENDING":
        return False, "Giao dịch không ở trạng thái chờ duyệt."
    if approve:
        db.execute("UPDATE actions SET reviewer=?, review_note=? WHERE id=?", (reviewer, (note or "")[:200], aid))
        out = execute_action(aid, via="REVIEW")
        return out["status"] == "EXECUTED", out.get("reason") or out["status"]
    db.execute("UPDATE actions SET status='REJECTED_BY_STAFF', reviewer=?, review_note=?, reason_public='Nhân viên chi nhánh từ chối giao dịch' WHERE id=?",
               (reviewer, (note or "")[:200], aid))
    bump_suspicion(r["customer_id"], 0.10)
    return True, "OK"
