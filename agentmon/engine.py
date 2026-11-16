"""
Pipeline quyết định (đúng sơ đồ yêu cầu):

  [1] Hard Policy (hạn mức cứng TSC→CN→KH, pháp lý Agent, số dư, PCI)  → vi phạm = BLOCK ngay, ML/LLM không ghi đè
  [2] Feature Engineering (hành vi riêng của từng khách + velocity)
  [3] Isolation Forest (điểm bất thường, mỗi domain 1 mô hình)
  [4] LLM Critic (Groq; chỉ được nâng mức, giải thích tiếng Việt)
  [5] Quyết định: ALLOW | KYA (khách xác nhận qua Authenticator) | REVIEW (nhân viên CN duyệt) | BLOCK
  [6] Lưu CSDL + thực hiện (hạch toán số dư) khi được phép
"""
import hashlib
import json
try:
    import fcntl
except ImportError:      # Windows: chỉ còn khóa trong tiến trình
    fcntl = None
import math
import re
import threading
import time

from agentmon import atm_identity, cardmodel, cards, fraudgbm, graphrisk, profiles, seqmodel, critic, db, features as F, fraud_types, kya, ml, policy, registry
from agentmon.constants import (ACTORS, CAP_KEY, CARD_KINDS, CNP_LIKE, CODE_VERSION, HUMAN_PREFIX, KIND_CHANNELS, ONLINE_SOURCES,
                                PAY_KINDS, SOURCE_SYSTEMS, WALLET_PROVIDERS)
from services.audit_log import add_log
from utils import store

class _EvalLock:
    """Khóa đánh giá/hạch toán: RLock trong tiến trình + khóa tệp (flock) giữa các tiến trình cùng máy.
    Cần thiết khi chạy gunicorn nhiều worker: kiểm tra số dư/hạn mức rồi ghi phải là một bước nguyên tử, kể cả khi
    FX và thanh toán của cùng khách đến đồng thời ở hai worker khác nhau. Nhiều MÁY → dùng PostgreSQL advisory lock (docs/DEPLOYMENT.md)."""

    def __init__(self):
        self._t = threading.RLock()
        self._depth = 0
        self._fh = None

    def __enter__(self):
        self._t.acquire()
        if self._depth == 0 and fcntl is not None:
            try:
                self._fh = open(db.path() + ".lock", "a")
                fcntl.flock(self._fh, fcntl.LOCK_EX)
            except OSError:
                self._fh = None
        self._depth += 1
        return self

    def __exit__(self, *exc):
        self._depth -= 1
        if self._depth == 0 and self._fh is not None:
            try:
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        self._t.release()
        return False


_eval_lock = _EvalLock()
ACTIVE_ST = ("EXECUTED", "PENDING_KYA", "REVIEW_PENDING", "PENDING_STEPUP")
ORDER = {"ALLOW": 0, "KYA": 1, "REVIEW": 2, "BLOCK": 3}
PUBLIC_MSG = {
    "ALLOW": "Giao dịch được chấp thuận và đã thực hiện.",
    "KYA": "Giao dịch bất thường – cần khách hàng xác minh (KYA) qua ứng dụng Authenticator trước khi thực hiện.",
    "REVIEW": "Giao dịch được giữ lại chờ nhân viên chi nhánh xét duyệt.",
    "BLOCK": "Giao dịch bị chặn.",
    "STEP_UP": "Giao dịch cần xác thực bổ sung (OTP/sinh trắc học) trước khi thực hiện.",
}
STEPUP_HOLD_SECONDS = 900          # giữ chỗ số dư cho giao dịch chờ xác thực bổ sung của NGƯỜI


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


def normalize(raw: dict, now: float, sim_hour=None, actor: str = "AGENT", source_system=None) -> dict:
    if not isinstance(raw, dict):
        raise BadRequest("Payload không hợp lệ.")
    if actor not in ACTORS:
        raise BadRequest("actor_type không hợp lệ.")
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
        if kind not in PAY_KINDS:
            raise BadRequest("kind phải là một trong: " + ", ".join(PAY_KINDS) + ".")
        a["amount_vnd"] = _num(raw.get("amount_vnd"), "amount_vnd")
        a["margin_vnd"] = None
        a["device_id"] = None
        chans = KIND_CHANNELS[kind]
        ch_raw = raw.get("channel_type")
        if ch_raw in (None, "") and actor == "HUMAN" and source_system in SOURCE_SYSTEMS:      # kênh mặc định theo hệ thống nguồn
            sc = SOURCE_SYSTEMS[source_system]["channel"]
            ch_raw = sc.get(kind) if isinstance(sc, dict) else sc
        ch = str(ch_raw).upper() if ch_raw not in (None, "") else chans[0]
        if ch not in chans:
            raise BadRequest(f"channel_type của {kind} phải là một trong: " + ", ".join(str(c) for c in chans if c) + ".")
        a["channel_type"] = ch
        if kind == "TRANSFER":
            ben = re.sub(r"\s", "", str(raw.get("beneficiary_account", "")))
            if not ben.isdigit() or not (6 <= len(ben) <= 20):
                raise BadRequest("beneficiary_account phải gồm 6–20 chữ số.")
            a["beneficiary"] = ben
            a["merchant"] = a["country"] = a["mcc"] = None
        else:
            a["card_token"] = str(raw.get("card_token", ""))[:64]
            # ATM dùng atm_id, hóa đơn dùng biller_id; còn lại merchant_id
            mid = raw.get("merchant_id") or (raw.get("atm_id") if kind == "ATM_WITHDRAWAL" else None) \
                or (raw.get("biller_id") if kind == "BILL_PAYMENT" else None) or ("ISSUER" if kind == "CARD_STATEMENT_PAYMENT" else None)
            a["merchant"] = str(mid or "")[:40] or None
            if not a["merchant"]:
                raise BadRequest({"ATM_WITHDRAWAL": "Thiếu atm_id.", "BILL_PAYMENT": "Thiếu biller_id."}.get(kind, "Thiếu merchant_id."))
            default_mcc = {"ATM_WITHDRAWAL": "6011", "BILL_PAYMENT": "4900", "CARD_STATEMENT_PAYMENT": "0000"}.get(kind, "")
            mcc = str(raw.get("mcc", default_mcc))
            if not re.fullmatch(r"\d{4}", mcc):
                raise BadRequest("mcc phải gồm 4 chữ số.")
            a["mcc"] = mcc
            ctry = str(raw.get("country", "VN")).upper()
            if not re.fullmatch(r"[A-Z]{2}", ctry):
                raise BadRequest("country phải là mã ISO 2 ký tự.")
            a["country"] = ctry
            if kind == "WALLET_PAYMENT":
                prov = str(raw.get("wallet_provider", "")).upper()
                if prov not in WALLET_PROVIDERS:
                    raise BadRequest("wallet_provider phải là một trong: " + ", ".join(WALLET_PROVIDERS) + ".")
                dev = re.sub(r"[^A-Za-z0-9_\-]", "", str(raw.get("device_id") or ""))[:64]
                if len(dev) < 6:
                    raise BadRequest("Thiếu device_id (≥ 6 ký tự) cho thanh toán ví điện tử.")
                a["wallet_provider"], a["device_id"] = prov, dev
            a["three_ds"] = bool(raw.get("three_ds"))
            a["beneficiary"] = None
            try:
                a.update(cardmodel.normalize(raw, kind, a["channel_type"], None))
            except ValueError as e:
                raise BadRequest(str(e))
    else:
        raise BadRequest("domain phải là FX hoặc PAY.")
    if kind == "ATM_WITHDRAWAL":
        _parse_atm_signals(raw, a)
    a["actor_type"], a["source_system"] = actor, source_system
    if actor == "HUMAN":
        if source_system not in SOURCE_SYSTEMS:
            raise BadRequest("source_system không hợp lệ.")
        if kind not in SOURCE_SYSTEMS[source_system]["kinds"]:
            raise BadRequest(f"Hệ thống nguồn {source_system} không gửi loại giao dịch {kind}.")
        sr = raw.get("session_risk", 0)
        try:
            sr = float(sr or 0)
        except (TypeError, ValueError):
            raise BadRequest("session_risk phải là số 0–100.")
        if not math.isfinite(sr) or not 0 <= sr <= 100:
            raise BadRequest("session_risk phải nằm trong 0–100 (điểm Anti-Bot).")
        a["session_risk"] = sr / 100.0
        dev = re.sub(r"[^A-Za-z0-9_\-]", "", str(raw.get("device_id") or ""))[:64]
        if dev and not a.get("device_id"):
            a["device_id"] = dev
    return a


_CAMERA = ("OK", "OBSTRUCTED", "TAMPERED", "OFFLINE")


def _parse_atm_signals(raw, a):
    """Tín hiệu Face-AI và hành vi tại ATM (do switch/camera ATM gửi). Embedding chỉ dùng tạm để so khớp, KHÔNG lưu."""
    b = raw.get("biometric")
    if b is not None:
        if not isinstance(b, dict):
            raise BadRequest("biometric phải là object.")
        out = {}

        def num(k, lo, hi, as_int=False):
            v = b.get(k)
            if v is None:
                return
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise BadRequest(f"biometric.{k} phải là số.")
            if not math.isfinite(f) or not lo <= f <= hi:
                raise BadRequest(f"biometric.{k} phải nằm trong {lo}–{hi}.")
            out[k] = int(f) if as_int else f
        num("faces_in_frame", 0, 20, True)
        for k in ("face_match_score", "liveness_score", "injection_attack_score", "occlusion", "capture_quality"):
            num(k, 0.0, 1.0)
        out["face_present"] = bool(b.get("face_present"))
        cam = str(b.get("camera_status", "OK")).upper()
        if cam not in _CAMERA:
            raise BadRequest("biometric.camera_status phải là một trong: " + ", ".join(_CAMERA) + ".")
        out["camera_status"] = cam
        emb = b.get("face_embedding")
        if emb is not None:
            if not isinstance(emb, list) or not (16 <= len(emb) <= 1024):
                raise BadRequest("biometric.face_embedding phải là danh sách số (16–1024 chiều).")
            try:
                a["_face_embedding"] = [float(x) for x in emb]
            except (TypeError, ValueError):
                raise BadRequest("biometric.face_embedding chứa giá trị không phải số.")
        a["biometric"] = out
    for k, lo, hi, as_int in (("pin_entry_cv", 0.0, 10.0, False), ("pin_digits", 0, 12, True), ("pin_attempts", 0, 10, True)):
        if raw.get(k) is not None:
            try:
                v = float(raw[k])
            except (TypeError, ValueError):
                raise BadRequest(f"{k} phải là số.")
            if not lo <= v <= hi:
                raise BadRequest(f"{k} phải nằm trong {lo}–{hi}.")
            a[k] = int(v) if as_int else v
    if raw.get("phone_near_atm") is not None:
        a["phone_near_atm"] = bool(raw["phone_near_atm"])


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
               "WHERE customer_id=? AND (status IN ('PENDING_KYA','REVIEW_PENDING') OR (status='PENDING_STEPUP' AND ts>?))",
               (customer_id, store.now() - STEPUP_HOLD_SECONDS))
    return bal, bal - res


def build_ctx(a, agent, customer, eff, now):
    cid = customer["customer_id"]
    dom = a["domain"]
    hist = db.query("SELECT * FROM actions WHERE customer_id=? AND domain=? AND status='EXECUTED' AND ts>? AND ts<=? AND sim!=2 "
                    "ORDER BY ts DESC LIMIT 600", (cid, dom, now - 365 * 86400, now))
    actor = a.get("actor_type") or "AGENT"
    human = actor == "HUMAN"
    # Baseline RIÊNG theo người thực hiện khi đủ dữ liệu (≥ 10 giao dịch của chính loại người đó); thiếu thì dùng baseline cấp khách hàng
    mine = [h for h in hist if ((h.get("actor_type") or "AGENT") == actor)]
    if len(mine) >= 10:
        hist = mine
    if human:
        att = db.query("SELECT ts, amount_vnd, decision, status, merchant FROM actions WHERE customer_id=? AND actor_type='HUMAN' AND ts>? AND ts<=? AND sim!=2 "
                       "ORDER BY ts DESC LIMIT 400", (cid, now - 86400, now))
    else:
        att = db.query("SELECT ts, amount_vnd, decision, status, merchant FROM actions WHERE agent_id=? AND ts>? AND ts<=? AND sim!=2 ORDER BY ts DESC LIMIT 400",
                       (agent["agent_id"], now - 86400, now)) if agent else []
    bal, avail = available_balance(cid)
    ds, ms = _day_start(now), _month_start(now)
    st = "('EXECUTED','PENDING_KYA','REVIEW_PENDING','PENDING_STEPUP') AND sim!=2"
    cum = {}
    if dom == "FX":
        cum["day"] = _sum(f"SELECT SUM(amount_usd) FROM actions WHERE customer_id=? AND domain='FX' AND status IN {st} AND ts>=?", (cid, ds))
    else:
        cum["day_transfer"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind='TRANSFER' AND status IN {st} AND ts>=?", (cid, ds))
        cum["month_transfer"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind='TRANSFER' AND status IN {st} AND ts>=?", (cid, ms))
        ck = "(" + ",".join(f"'{k}'" for k in CARD_KINDS) + ")"
        cum["day_card"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind IN {ck} AND status IN {st} AND ts>=?", (cid, ds))
        cum["day_atm"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE customer_id=? AND kind='ATM_WITHDRAWAL' AND status IN {st} AND ts>=?", (cid, ds))
        if a.get("card_id"):
            cum["day_this_card"] = _sum(f"SELECT SUM(amount_vnd) FROM actions WHERE card_id=? AND status IN {st} AND ts>=?", (a["card_id"], ds))
    cum["hour_n"] = _sum("SELECT COUNT(*) FROM actions WHERE agent_id=? AND decision!='BLOCK' AND sim!=2 AND ts>?", (agent["agent_id"], now - 3600)) if agent else 0
    cum["day_n"] = _sum("SELECT COUNT(*) FROM actions WHERE agent_id=? AND decision!='BLOCK' AND sim!=2 AND ts>=?", (agent["agent_id"], ds)) if agent else 0
    trusted = {r["account"] for r in db.query("SELECT account FROM trusted_beneficiaries WHERE customer_id=?", (cid,))}
    onl = db.one("SELECT COUNT(*) n, MAX(ts) m FROM actions WHERE customer_id=? AND status='EXECUTED' AND channel IN ('AGENT','ONLINE','PORTAL','DIGIBANK','DIGIBIZ') AND sim!=2 AND ts<=?", (cid, now))
    last = db.one("SELECT MAX(ts) m FROM actions WHERE customer_id=? AND status='EXECUTED' AND sim!=2 AND ts<=?", (cid, now))
    fl = db.one("SELECT * FROM flags WHERE customer_id=?", (cid,)) or {}
    ctx = F.Ctx(dom, now, hist, att, avail, eff, trusted, online_exec_any=int(onl["n"] or 0), last_exec_ts=last["m"],
                agent_prior=int(db.one("SELECT COUNT(*) n FROM actions WHERE agent_id=?", (agent["agent_id"],))["n"]) if agent else 0,
                probation_left=int(agent["probation_left"] or 0) if agent else 0, suspicion=float(fl.get("suspicion") or 0),
                watchlist=bool(fl.get("watchlist")), cum=cum)
    ctx.balance_total = bal
    # Tín hiệu chéo FX ↔ Thanh toán: số lệnh của chính khách ở phân hệ KHÁC trong 5 phút (mọi Agent của khách)
    ctx.actor = actor
    try:      # đồ thị liên kết: số khách khác nối qua thiết bị/người nhận/IP trong 7 ngày
        ctx.ring_size = graphrisk.ring_size(cid, a.get("device_id"), a.get("beneficiary"), a.get("_ip"), now)
    except Exception:      # noqa: BLE001  (tín hiệu bổ sung không được làm hỏng quyết định)
        ctx.ring_size = 0
    # Người ↔ Agent: số giao dịch của loại người thực hiện NGƯỢC LẠI trên cùng tài khoản trong 10 phút
    ctx.cross_actor_n10 = int(_sum("SELECT COUNT(*) FROM actions WHERE customer_id=? AND COALESCE(actor_type,'AGENT')!=? AND sim!=2 AND ts>? AND ts<=?",
                                   (cid, actor, now - 600, now)))
    # Tài khoản trung gian (mule): số KHÁC khách đã chuyển tới cùng người nhận trong 24 giờ
    if a.get("kind") == "TRANSFER" and a.get("beneficiary"):
        ctx.benef_senders = int(_sum("SELECT COUNT(DISTINCT customer_id) FROM actions WHERE beneficiary=? AND kind='TRANSFER' AND customer_id!=? "
                                     "AND decision!='BLOCK' AND sim!=2 AND ts>? AND ts<=?", (a["beneficiary"], cid, now - 86400, now)))
    ctx.cross_n5 = _sum("SELECT COUNT(*) FROM actions WHERE customer_id=? AND domain!=? AND sim!=2 AND ts>? AND ts<=?", (cid, dom, now - 300, now))
    return ctx


def hard_policy(a, agent, customer, eff, ctx, pci_violation):
    """Trả danh sách lý do vi phạm cứng. Rỗng = hợp lệ."""
    R = []
    human = a.get("actor_type") == "HUMAN"
    ks = policy.kill_switch()
    if ks.get("on") and not human:           # kill-switch dành cho AI Agent, không chặn giao dịch của người
        R.append(f"TSC đã bật KILL-SWITCH toàn hệ thống: {ks.get('reason') or 'tạm dừng AI Agent'}")
    if not human:
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
    if not customer.get("online") and (not human or a.get("source_system") in ONLINE_SOURCES):
        R.append("CIF chưa được chi nhánh bật dịch vụ online")
    if (a.get("atm_identity") or {}).get("hard"):
        R.append(a["atm_identity"]["hard"])
    if pci_violation:
        R.append("PCI-DSS: payload chứa số thẻ đầy đủ/CVV/PIN – Agent chỉ được dùng token thẻ")
    g = eff["_global"]
    amt = a["amount_usd"] if a["domain"] == "FX" else a["amount_vnd"]
    if not human and ctx.cum.get("hour_n", 0) >= float(eff["per_hour"]):
        R.append(f"Vượt số giao dịch/giờ ({eff['per_hour']:g})")
    if not human and ctx.cum.get("day_n", 0) >= float(eff["per_day"]):
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
            elif a["kind"] != "CARD_STATEMENT_PAYMENT":      # thanh toán dư nợ sao kê: chỉ cần thẻ thuộc khách (thẻ khóa/hết hạn vẫn được trả nợ)
                if card["status"] != "ACTIVE":
                    R.append(f"Thẻ {card['network']} …{card['last4']} đang ở trạng thái {card['status']}")
                if cards.expired(card["exp_month"], card["exp_year"], a["ts"]):
                    R.append("Thẻ đã hết hạn")
                if a["channel_type"] in CNP_LIKE and not card["cnp_enabled"]:
                    R.append("Thẻ chưa bật thanh toán online (CNP)")
                if a["country"] != "VN" and not card["intl_enabled"]:
                    R.append("Thẻ chưa bật giao dịch quốc tế")
                if card.get("per_txn_limit") and a["amount_vnd"] > float(card["per_txn_limit"]):
                    R.append(f"Vượt hạn mức/giao dịch của thẻ ({float(card['per_txn_limit']):,.0f})")
                if card.get("daily_limit") and ctx.cum.get("day_this_card", 0) + a["amount_vnd"] > float(card["daily_limit"]):
                    R.append(f"Vượt hạn mức/ngày của thẻ ({float(card['daily_limit']):,.0f})")
            capkey = CAP_KEY.get(a["kind"], "card_per_txn")
            cap = float(eff[capkey])
            if a["amount_vnd"] > cap:
                R.append(f"Giá trị {a['amount_vnd']:,.0f} VND vượt hạn mức {policy.LABELS.get(capkey, 'thẻ')} ({cap:,.0f})")
            if a["kind"] == "ATM_WITHDRAWAL" and ctx.cum.get("day_atm", 0) + a["amount_vnd"] > float(eff["atm_daily"]):
                R.append(f"Vượt hạn mức rút ATM ngày {float(eff['atm_daily']):,.0f} VND")
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
        "reasons,triggers,reason_public,llm,source,sim,channel_type,device_id,fraud_class,fraud_types,model_version,trace_hash,"
        "actor_type,source_system,session_risk) VALUES(" + ",".join("?" * 42) + ")",
        (ts, a["domain"], a["kind"], customer_id, branch_id, agent_id, a.get("source_system") or "AGENT", a.get("client_ref"), a.get("amount_vnd"),
         a.get("amount_usd"), a.get("pair"), a.get("side"), a.get("leverage"), a.get("beneficiary"), a.get("merchant"),
         a.get("mcc"), a.get("country"), (a.get("card") or {}).get("card_id"), a["hour"], db.jdump(details),
         res.get("anomaly"), res.get("behavior"), res.get("velocity"), res.get("final_risk"), res["decision"], res["status"],
         res.get("hard_reason"), db.jdump(res.get("reasons", [])), db.jdump(res.get("triggers", [])), res["reason_public"],
         db.jdump(res.get("llm")), source, 1 if sim else 0, a.get("channel_type"), a.get("device_id"), res.get("fraud_class"),
         db.jdump(res.get("fraud_types", [])), res.get("model_version"), res.get("trace_hash"),
         a.get("actor_type") or "AGENT", a.get("source_system"), a.get("session_risk")))


def bump_suspicion(customer_id, delta):
    if not customer_id:
        return
    r = db.one("SELECT suspicion FROM flags WHERE customer_id=?", (customer_id,))
    s = min(1.0, max(0.0, (float(r["suspicion"]) if r else 0.0) + delta))
    db.execute("INSERT INTO flags(customer_id,suspicion,watchlist,updated_at) VALUES(?,?,?,?) ON CONFLICT(customer_id) DO UPDATE "
               "SET suspicion=excluded.suspicion, watchlist=excluded.watchlist, updated_at=excluded.updated_at",
               (customer_id, s, 1 if s > 0.7 else 0, store.now()))


def _canon(o):
    return json.loads(json.dumps(o, ensure_ascii=False, default=str))


def trace_hash(trace) -> str:
    """SHA-256 của trace chuẩn hóa – lưu kèm quyết định để phát hiện sửa đổi sau này."""
    return hashlib.sha256(json.dumps(_canon(trace), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def build_trace(a, eff, ctx, hard, vec, comps, path, trig, llm, fraud, used_model):
    """Bản ghi giải trình đầy đủ để TÁI LẬP quyết định: mô hình (version+SHA), ngưỡng, trọng số, hạn mức hiệu lực,
    vector đặc trưng, thành phần điểm, đường quyết định, trigger, LLM, phân loại gian lận. Không chứa PAN/CVV."""
    g = eff["_global"]
    try:
        mref = ml.model_ref(a["domain"])
    except Exception as ex:      # noqa: BLE001
        mref = {"domain": a["domain"], "error": str(ex)[:80]}
    mref["used_for_this_decision"] = bool(used_model)
    try:
        fl = F.context_flags(a, ctx)
        base = {"history_n": fl["st"]["n"], "same_kind_n": fl["st"]["n_kind"], "mean": round(fl["st"]["mean"], 2),
                "std": round(fl["st"]["std"], 2), "ratio": round(fl["ratio"], 3), "z": round(fl["z"], 3), "thin_history": fl["thin"]}
    except Exception:      # noqa: BLE001
        base = None
    return {
        "schema": "decision-trace/1", "code_version": CODE_VERSION, "evaluated_at": a["ts"],
        "input": {k: a.get(k) for k in ("domain", "kind", "channel_type", "amount_vnd", "amount_usd", "pair", "side", "leverage", "hour",
                                         "country", "mcc", "wallet_provider", "actor_type", "source_system")},
        "model": mref,
        "scoring": {"weights": {"ml": F.W_ML, "behavior": F.W_BEH, "velocity": F.W_VEL, "blend_mean": F.W_BLEND_MEAN,
                                "blend_max": F.W_BLEND_MAX, "watchlist_bonus": F.WATCHLIST_BONUS},
                    "thresholds": {"kya": g.get("kya_threshold"), "review": g.get("review_threshold"), "block": g.get("block_threshold")},
                    "components": comps},
        "features": vec, "baseline": base,
        "limits_effective": {k: v for k, v in eff.items() if k != "_global"},
        "policy_global": g,
        "hard_violations": hard, "triggers": [t[0] for t in trig], "decision_path": path,
        "llm": {"configured": critic.status(), "called": llm is not None,
                "recommendation": (llm or {}).get("recommendation"), "source": (llm or {}).get("source")},
        "fraud": fraud, "pre_screen": a.get("_pre"), "atm_identity": a.get("atm_identity"),
        "context": {"available_balance": round(float(ctx.balance), 2), "suspicion": ctx.suspicion, "watchlist": ctx.watchlist,
                    "probation_left": ctx.probation_left, "attempts_24h": len(ctx.attempts), "cross_domain_n5": getattr(ctx, "cross_n5", 0),
                    "actor_type": a.get("actor_type"), "source_system": a.get("source_system"), "session_risk": a.get("session_risk"),
                    "cross_actor_n10": ctx.cross_actor_n10, "benef_senders": ctx.benef_senders},
    }


def _classify_safe(a, ctx, trig, final, pci, kya_thr):
    try:
        return fraud_types.classify(a, ctx, trig, final_risk=final, pci=pci, kya_threshold=kya_thr)
    except Exception as ex:      # noqa: BLE001  (lớp giải thích không được làm hỏng quyết định)
        return {"class": None, "types": [], "anomaly_codes": [], "handling": "", "error": str(ex)[:80]}


def evaluate(raw: dict, agent_id: str, source: str = "AGENT_API", customer_hint: str = "", sim_hour=None,
             sim_ts=None, ip: str = "", use_llm: bool = True, actor: str = "AGENT", source_system=None, pre=None) -> dict:
    """actor=AGENT: giao dịch do AI Agent gửi (agent_id = mã Agent). actor=HUMAN: giao dịch của NGƯỜI từ hệ thống nguồn
    (portal/Digibank/Digibiz/switch thẻ/ATM/IPS); khi đó cần customer_hint, agent_id được đặt = 'HUMAN:<source_system>'.
    Với người: không cần đăng ký Agent, KYA được thay bằng STEP_UP (OTP/sinh trắc do kênh thực hiện), không gọi LLM mặc định."""
    from app.customer.mock_db import get_demo_customer
    now = float(sim_ts) if sim_ts else store.now()
    pci = cards.find_pan_in(raw)
    safe_raw = cards.redact(raw)
    human = actor == "HUMAN"
    if human:
        agent_id = HUMAN_PREFIX + str(source_system)
        if not customer_hint:
            raise BadRequest("Thiếu customer_id cho giao dịch của người dùng.")
    a = normalize(safe_raw, now, sim_hour, actor, source_system)     # chuẩn hóa trên bản đã che PAN
    if pre:                       # kết quả sàng lọc Anti-Bot + phân loại người thực hiện (pipeline v2)
        a["actor_unverified"] = bool((pre.get("actor") or {}).get("unverified"))
        a["actor_confidence"] = (pre.get("actor") or {}).get("confidence")
        a["_pre"] = pre
        a["_ip"] = pre.get("ip")
    with _eval_lock:
        agent = None if human else registry.get(agent_id)
        if a.get("client_ref") and (agent or human):
            ex = db.one("SELECT id FROM actions WHERE agent_id=? AND client_ref=?", (agent_id, a["client_ref"]))
            if ex:
                return get_action_result(ex["id"], duplicate=True)
        cid = agent["customer_id"] if agent else customer_hint
        customer = get_demo_customer(cid) if cid else None
        customer = customer or {"customer_id": cid or "UNKNOWN", "segment": "STANDARD", "status": "UNKNOWN", "online": False, "branch_id": ""}
        domain_limits = (agent or {}).get("limits", {}).get(a["domain"], {}) if agent else {}
        eff = policy.effective_limits(a["domain"], customer.get("segment", "STANDARD"), cid, domain_limits)
        if a["domain"] == "PAY" and a["kind"] != "TRANSFER" and (agent or human):
            c = db.one("SELECT * FROM cards WHERE token=? AND customer_id=?", (a.get("card_token", ""), cid))
            if c:
                a["card"] = c
                a["card_id"] = c["card_id"]
                if not a.get("card_network") or a["card_network"] == "OTHER":
                    n_ = str(c.get("network") or "").upper()
                    a["card_network"] = n_ if n_ in cardmodel.NETWORKS else cardmodel.network_from_bin(c.get("bin6"))
        if a["kind"] == "ATM_WITHDRAWAL":
            # AI nhận diện danh tính tại ATM: chính khách / người khác / không có người / giả mạo (chỉ áp cho giao dịch NGƯỜI qua switch ATM)
            bio = None
            if human and a.get("biometric") is not None:
                bio = dict(a["biometric"], _face_embedding=a.get("_face_embedding"))
            a["customer_id"] = cid
            ai = atm_identity.assess(a, bio, eff["_global"], now) if human else {"verdict": "AGENT_ON_ATM", "who": "UNKNOWN", "floor": "ALLOW", "step_up_method": None,
                                                                              "triggers": [], "fraud": [], "hard": None, "advice": [], "behavior": [], "face": None}
            a["atm_identity"], a["atm_triggers"], a["atm_fraud"] = ai, ai["triggers"], ai["fraud"]
        a.pop("_face_embedding", None)
        ctx = build_ctx(a, agent, customer, eff, now)
        hard = hard_policy(a, agent, customer, eff, ctx, pci)
        details = {k: v for k, v in a.items() if k not in ("card", "card_token", "ts", "_pre", "_ip", "atm_triggers", "atm_fraud")}
        details["card_last4"] = (a.get("card") or {}).get("last4")
        details["pci_violation"] = pci
        details["pre_screen"] = pre
        res = {"reasons": [], "triggers": [], "llm": None}
        path, vec, comps, llm, trig_all = [], None, None, None, []
        if hard:
            path.append(f"HARD_POLICY: {len(hard)} vi phạm → BLOCK (ML/LLM không được ghi đè)")
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
            final = F.blend(an, beh, vel, ctx.watchlist)     # ML đơn độc không kéo điểm lên – cần hành vi/velocity đồng thuận
            if ctx.watchlist:
                why_b.append("Khách hàng đang trong danh sách theo dõi (suspicion cao)")
            trig = F.triggers(a, ctx)
            trig_all = trig
            try:      # ý kiến thứ hai: gradient boosting có giám sát (shadow: chỉ ghi; active: chỉ được NÂNG cảnh báo)
                gp = fraudgbm.prob(a["domain"], vec, beh, vel)
                gmode = profiles.ensemble_mode()
                if gmode == "active" and gp >= fraudgbm.HIGH:
                    trig = list(trig) + [("SUPERVISED_HIGH_RISK", f"Mô hình giám sát thứ hai đánh giá rủi ro cao ({gp:.2f})")]
                    trig_all = trig
                gbm_info = {"prob": round(gp, 4), "mode": gmode, "version": fraudgbm.version(a["domain"])}
            except Exception as ex:      # noqa: BLE001
                gbm_info = {"error": str(ex)[:60]}
            sq = seqmodel.surprise(ctx.hist, a)
            comps = {"anomaly": round(an, 4), "behavior": round(beh, 4), "velocity": round(vel, 4),
                     "final": round(final, 4), "watchlist_bonus_applied": bool(ctx.watchlist),
                     "supervised_gbm": gbm_info, "sequence_surprise": None if sq is None else round(sq, 3), "ring_size": ctx.ring_size}
            path.append("HARD_POLICY: đạt")
            g = eff["_global"]
            if final >= float(g["block_threshold"]):
                dec = "BLOCK"
            elif final >= float(g["review_threshold"]):
                dec = "REVIEW"
            elif final >= float(g["kya_threshold"]) or trig:
                dec = "KYA"
            else:
                dec = "ALLOW"
            path.append(f"SCORE: final={final:.3f} (ML {an:.2f} · hành vi {beh:.2f} · velocity {vel:.2f}) → {dec} theo ngưỡng"
                        f" KYA {g['kya_threshold']}/REVIEW {g['review_threshold']}/BLOCK {g['block_threshold']}"
                        + (f"; trigger bắt buộc KYA: {', '.join(t[0] for t in trig)}" if trig else ""))
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
                    path.append(f"LLM_CRITIC: nâng {dec}→{rec}")
                    dec = rec
            _ai = a.get("atm_identity") or {}
            if _ai.get("floor") == "REVIEW" and dec in ("ALLOW", "KYA"):
                dec = "REVIEW"
                path.append("ATM_IDENTITY: camera bị che/can thiệp + số tiền lớn → nâng lên REVIEW")
            if human and dec == "KYA":
                dec = "STEP_UP"
                path.append("STEP_UP: giao dịch của NGƯỜI cần xác thực bổ sung (OTP/sinh trắc) do kênh nguồn thực hiện")
            if dec == "KYA":
                if not kya.enrolled(cid):
                    dec = "BLOCK"
                    path.append("FAIL_CLOSED: cần KYA nhưng chưa có Authenticator → BLOCK")
                    reasons.append("Cần KYA nhưng khách hàng CHƯA đăng ký Authenticator (fail-closed)")
                elif _sum("SELECT COUNT(*) FROM kya WHERE customer_id=? AND status='PENDING'", (cid,)) >= int(g["max_pending_kya"]):
                    dec = "BLOCK"
                    path.append("FAIL_CLOSED: quá nhiều KYA đang chờ → BLOCK")
                    reasons.append("Quá nhiều yêu cầu KYA đang chờ (chống dội thông báo xác minh)")
            status = {"ALLOW": "PENDING_EXEC", "KYA": "PENDING_KYA", "STEP_UP": "PENDING_STEPUP", "REVIEW": "REVIEW_PENDING", "BLOCK": "BLOCKED"}[dec]
            pub = PUBLIC_MSG[dec]
            if dec == "BLOCK":
                pub = "Giao dịch bị chặn do mức rủi ro quá cao." if not reasons or "Authenticator" not in reasons[-1] else "Bị chặn: " + reasons[-1]
            res.update(decision=dec, status=status, final_risk=round(final, 4), anomaly=round(an, 4), behavior=round(beh, 4),
                       velocity=round(vel, 4), reasons=reasons, triggers=[list(t) for t in trig], llm=llm, reason_public=pub)
            if dec in ("KYA", "STEP_UP", "REVIEW", "BLOCK"):
                bump_suspicion(cid, {"KYA": 0.05, "STEP_UP": 0.05, "REVIEW": 0.15, "BLOCK": 0.30}[dec])
        g_ = eff["_global"]
        if hard:
            trig_all = F.triggers(a, ctx)
        fraud = _classify_safe(a, ctx, trig_all, res.get("final_risk"), pci, float(g_.get("kya_threshold", 0.35)))
        res["fraud_class"] = fraud.get("class")
        res["fraud_types"] = [t["code"] for t in fraud.get("types", [])]
        details["fraud"] = fraud
        used_model = not hard
        tr = build_trace(a, eff, ctx, hard, vec, comps, path, trig_all, res.get("llm"), fraud, used_model)
        details["trace"] = tr
        res["trace_hash"] = trace_hash(tr)
        res["model_version"] = (tr["model"].get("version") if used_model else None)
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
    for k in ("details", "reasons", "triggers", "llm", "fraud_types"):
        d[k] = db.jload(d.get(k), [] if k in ("reasons", "triggers", "fraud_types") else None)
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
        if r["status"] not in ("PENDING_EXEC", "PENDING_KYA", "REVIEW_PENDING", "PENDING_STEPUP"):
            return {"status": r["status"]}
        human = r.get("actor_type") == "HUMAN"
        need = (r["amount_vnd"] / (r["leverage"] or 1)) if r["domain"] == "FX" else r["amount_vnd"]
        acc = c.execute("SELECT balance_vnd FROM accounts WHERE customer_id=?", (r["customer_id"],)).fetchone()
        bal = float(acc["balance_vnd"]) if acc else 0.0
        ag = None if human else c.execute("SELECT status FROM agents WHERE agent_id=?", (r["agent_id"],)).fetchone()
        fail = None
        if not human and policy.kill_switch().get("on"):
            fail = "TSC đang bật kill-switch"
        elif not human and (not ag or ag["status"] != "ACTIVE"):
            fail = "Agent không còn ở trạng thái hoạt động"
        elif need > bal:
            fail = "Số dư không đủ tại thời điểm thực hiện"
        if fail:
            c.execute("UPDATE actions SET status='FAILED', reason_public=? WHERE id=?", ("Không thực hiện được: " + fail, aid))
            return {"status": "FAILED", "reason": fail}
        c.execute("UPDATE accounts SET balance_vnd=balance_vnd-? WHERE customer_id=?", (need, r["customer_id"]))
        c.execute("UPDATE actions SET status='EXECUTED', executed_at=?, reason_public=? WHERE id=?",
                  (store.now(), "Giao dịch đã thực hiện" + (f" (xác minh: {via})" if via != "AUTO" else ""), aid))
    if via.startswith("KYA") or via == "STEPUP":
        bump_suspicion(r["customer_id"], -0.05)
    add_log("agent_action_executed", user_id=r["agent_id"], customer_id=r["customer_id"] or "", detail={"action_id": aid, "via": via})
    return {"status": "EXECUTED"}


def step_up_result(aid, passed: bool, source_system=None):
    """Kênh nguồn báo kết quả xác thực bổ sung (OTP/sinh trắc) của NGƯỜI dùng: đạt → thực hiện; không đạt/hết hạn → chặn."""
    r = db.one("SELECT * FROM actions WHERE id=?", (aid,))
    if not r or r.get("actor_type") != "HUMAN":
        return {"status": "NOT_FOUND"}
    if source_system and r.get("source_system") != source_system:
        return {"status": "FORBIDDEN"}
    if r["status"] != "PENDING_STEPUP":
        return {"status": r["status"]}
    if store.now() - r["ts"] > STEPUP_HOLD_SECONDS:
        db.execute("UPDATE actions SET status='STEPUP_EXPIRED', reason_public='Hết thời gian xác thực bổ sung' WHERE id=?", (aid,))
        return {"status": "STEPUP_EXPIRED"}
    if passed:
        return execute_action(aid, via="STEPUP")
    db.execute("UPDATE actions SET status='STEPUP_FAILED', reason_public='Xác thực bổ sung không thành công' WHERE id=?", (aid,))
    bump_suspicion(r["customer_id"], 0.20)
    add_log("human_stepup_failed", user_id=r["agent_id"], customer_id=r["customer_id"] or "", level="warn", detail={"action_id": aid})
    return {"status": "STEPUP_FAILED"}


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
