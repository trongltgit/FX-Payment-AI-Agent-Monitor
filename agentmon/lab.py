"""Test Lab: kịch bản kiểm thử toàn bộ pipeline (chỉ bật ở demo hoặc AGENTMON_LAB=1)."""
import os

from agentmon import db, engine, policy, registry
from app.customer.mock_db import get_demo_customer
from utils import store

TEST_PAN = "4111111111111111"


def enabled():
    return os.environ.get("PRICING_ENVIRONMENT", "demo").lower() != "production" or os.environ.get("AGENTMON_LAB") == "1"


def _agent_for(cid, domain):
    ags = [a for a in registry.list_agents([cid]) if domain in a["domains"] and a["status"] != "REJECTED"]
    for a in ags:                      # ưu tiên Agent đang hoạt động; nếu không có thì dùng Agent bất kỳ để thấy lý do bị chặn
        if a["status"] == "ACTIVE":
            return a["agent_id"]
    return ags[0]["agent_id"] if ags else None


def _usual(cid, domain):
    rows = db.query("SELECT * FROM actions WHERE customer_id=? AND domain=? AND status='EXECUTED' AND source='SEED' ORDER BY ts DESC LIMIT 300", (cid, domain))
    u = {"n": len(rows)}
    if domain == "FX":
        amts = sorted(r["amount_usd"] for r in rows if r["amount_usd"])
        u["amt"] = amts[len(amts) // 2] if amts else 5000
        pairs = [r["pair"] for r in rows if r["pair"]]
        u["pair"] = max(set(pairs), key=pairs.count) if pairs else "USDVND"
        u["lev"] = sorted(r["leverage"] for r in rows if r["leverage"])[len(rows) // 2] if rows else 2
    else:
        tr = sorted(r["amount_vnd"] for r in rows if r["kind"] == "TRANSFER")
        u["tamt"] = tr[len(tr) // 2] if tr else 3_000_000
        ben = [r["beneficiary"] for r in rows if r["beneficiary"]]
        u["ben"] = max(set(ben), key=ben.count) if ben else "1234567890"
        cd = sorted(r["amount_vnd"] for r in rows if r["kind"] != "TRANSFER")
        u["camt"] = cd[len(cd) // 2] if cd else 1_000_000
        mer = [(r["merchant"], r["mcc"], r["country"]) for r in rows if r["merchant"]]
        u["mer"] = max(set(mer), key=mer.count) if mer else ("M300", "5411", "VN")
    hrs = [r["hour"] for r in rows if r["hour"] is not None]
    u["hour"] = max(set(hrs), key=hrs.count) if hrs else 10
    return u


def _card(cid, need_intl=False):
    cs = db.query("SELECT * FROM cards WHERE customer_id=? AND status='ACTIVE' ORDER BY intl_enabled DESC, created_at", (cid,))
    return cs[0]["token"] if cs else "tok_none"


def _eff(cid, domain, agent):
    cust = get_demo_customer(cid)
    a = registry.get(agent) if agent else None
    return policy.effective_limits(domain, cust["segment"], cid, (a or {}).get("limits", {}).get(domain))


def _fx(pair, usd, lev=1, **kw):
    return dict(raw=dict(domain="FX", kind="FX_TRADE", pair=pair, side="BUY", notional_usd=usd, leverage=lev), **kw)


def _t(amt, ben, **kw):
    return dict(raw=dict(domain="PAY", kind="TRANSFER", amount_vnd=amt, beneficiary_account=ben), **kw)


def _c(kind, amt, tok, mer, mcc, ctry, d3=True, **kw):
    return dict(raw=dict(domain="PAY", kind=kind, amount_vnd=amt, card_token=tok, merchant_id=mer, mcc=mcc, country=ctry, three_ds=d3), **kw)


SCEN = [
    ("FX-01", "FX", "Lệnh FX bình thường", "Cặp, giá trị, đòn bẩy, giờ đúng thói quen khách → ALLOW", "ALLOW"),
    ("FX-02", "FX", "Vượt hạn mức / lệnh", "Giá trị 1,5× hạn mức hiệu lực → BLOCK (hard policy)", "BLOCK"),
    ("FX-03", "FX", "Vượt đòn bẩy tối đa", "Đòn bẩy = trần + 5 → BLOCK", "BLOCK"),
    ("FX-04", "FX", "Cặp tiền không được phép", "XAUUSD không có trong danh mục → BLOCK", "BLOCK"),
    ("FX-05", "FX", "Lệnh lớn lúc 3h sáng", "Gấp 3,5× thói quen + ngoài giờ → KYA hoặc REVIEW", "KYA/REVIEW"),
    ("FX-06", "FX", "Vượt ngưỡng bắt buộc KYA", "Giá trị ≥ ngưỡng KYA (vẫn trong hạn mức) → chờ xác minh Authenticator", "KYA"),
    ("FX-07", "FX", "Đòn bẩy tăng đột biến", "Đòn bẩy gấp nhiều lần thói quen → KYA", "KYA"),
    ("FX-08", "FX", "Dồn dập 12 lệnh / 4 phút", "Velocity/anti-bot: các lệnh sau bị nâng mức", "MIXED"),
    ("FX-09", "FX", "Cạn hạn mức ngày", "Lặp lệnh 40% hạn mức ngày → lệnh thứ 3 bị BLOCK", "MIXED"),
    ("FX-10", "FX", "Ký quỹ vượt số dư", "Hạ số dư tiền gửi thanh toán rồi gửi lệnh → BLOCK", "BLOCK"),
    ("FX-11", "FX", "Agent chưa đăng ký", "agent-ghost không có trong Registry → BLOCK", "BLOCK"),
    ("PAY-01", "PAY", "Chuyển tiền thường lệ", "Người nhận quen, số tiền trung bình → ALLOW", "ALLOW"),
    ("PAY-02", "PAY", "Mua sắm online thường lệ", "Merchant quen, 3DS, nước quen → ALLOW", "ALLOW"),
    ("PAY-03", "PAY", "Vượt hạn mức chuyển tiền / lần", "1,2× hạn mức → BLOCK", "BLOCK"),
    ("PAY-04", "PAY", "Vượt số dư tiền gửi thanh toán", "Hạ số dư rồi chuyển khoản → BLOCK", "BLOCK"),
    ("PAY-05", "PAY", "Người nhận mới – số tiền lớn", "Vượt ngưỡng người nhận mới → KYA", "KYA"),
    ("PAY-06", "PAY", "KH lần đầu giao dịch online", "CUST004 (chỉ có lịch sử quầy) – sau khi CN duyệt agent-pay-004 → KYA FIRST_ONLINE", "KYA"),
    ("PAY-07", "PAY", "Tài khoản ngủ đông thức dậy", "Dùng CUST003 (110+ ngày không giao dịch) → KYA DORMANT_WAKE", "KYA"),
    ("PAY-08", "PAY", "Agent gửi số thẻ đầy đủ (PAN)", "PCI-DSS: chặn + che số thẻ trong log", "BLOCK"),
    ("PAY-09", "PAY", "Agent gửi CVV", "Không bao giờ nhận/lưu CVV → BLOCK", "BLOCK"),
    ("PAY-10", "PAY", "MCC bị cấm (cờ bạc 7995)", "Danh mục bị chặn toàn hệ thống → BLOCK", "BLOCK"),
    ("PAY-11", "PAY", "Quốc gia rủi ro cao + không 3DS", "NG, MCC 5967, CNP không 3DS → KYA/REVIEW (hoặc BLOCK nếu thẻ chưa bật quốc tế)", "KYA/REVIEW"),
    ("PAY-12", "PAY", "Dò thẻ (card testing)", "8 giao dịch 5.000đ/10 phút khác merchant → bị nâng mức", "MIXED"),
    ("PAY-13", "PAY", "Né hạn mức (structuring)", "3 lần chuyển sát 95% hạn mức → bị nâng mức", "MIXED"),
    ("PAY-14", "PAY", "Rút gần hết số dư", "Chuyển ≈85% số dư → KYA BALANCE_DRAIN", "KYA"),
    ("PAY-15", "PAY", "Agent chưa được duyệt", "Dùng agent-pay-004 (PENDING) → BLOCK", "BLOCK"),
    ("PAY-16", "PAY", "Thẻ không có token hợp lệ", "tok_fake → BLOCK", "BLOCK"),
]


def catalog(domain=None):
    return [dict(id=s[0], domain=s[1], title=s[2], desc=s[3], expected=s[4]) for s in SCEN if not domain or s[1] == domain]


def _set_balance(cid, v):
    """Đặt số dư KHẢ DỤNG = v (cộng thêm phần đang bị giữ cho giao dịch chờ KYA/duyệt)."""
    bal, avail = engine.available_balance(cid)
    db.execute("UPDATE accounts SET balance_vnd=? WHERE customer_id=?", (v + (bal - avail), cid))


def build(sid, cid):
    """Trả (agent_id, steps, note). Mỗi step: raw, sim_hour?, dt (giây lệch so với now), pre (hành động chuẩn bị)."""
    dom = "FX" if sid.startswith("FX") else "PAY"
    ag = _agent_for(cid, dom)
    if sid == "PAY-15":
        ag = "agent-pay-004"
    if sid in ("FX-11",):
        ag = "agent-ghost"
    u = _usual(cid, dom)
    eff = _eff(cid, dom, ag if ag and ag not in ("agent-ghost",) else None)
    note = ""
    if not ag:
        return None, [], f"Khách {cid} chưa đăng ký Agent {dom}. Hãy đăng ký + duyệt Agent hoặc chọn CUST001/002/005 (FX), CUST001/002/003/005 (PAY)."
    S = []
    h = u["hour"]
    if dom == "FX":
        cap, lvmax = float(eff["per_order_usd"]), float(eff["max_leverage"])
        lev_ok = min(float(u["lev"]), lvmax)
        if sid == "FX-01": S = [_fx(u["pair"], u["amt"], lev_ok, sim_hour=h)]
        elif sid == "FX-02": S = [_fx(u["pair"], cap * 1.5, 1, sim_hour=h)]
        elif sid == "FX-03": S = [_fx(u["pair"], u["amt"], lvmax + 5, sim_hour=h)]
        elif sid == "FX-04": S = [_fx("XAUUSD", u["amt"], 1, sim_hour=h)]
        elif sid == "FX-05": S = [_fx(u["pair"], min(u["amt"] * 3.5, cap), lev_ok, sim_hour=3)]
        elif sid == "FX-06": S = [_fx(u["pair"], min(float(eff["kya_above_usd"]) * 1.05, cap), 1, sim_hour=h)]
        elif sid == "FX-07": S = [_fx(u["pair"], u["amt"], min(max(lev_ok * 3.2, 11), lvmax), sim_hour=h)]
        elif sid == "FX-08": S = [_fx(u["pair"], u["amt"], lev_ok, sim_hour=h, dt=-300 + i * 22) for i in range(12)]
        elif sid == "FX-09": S = [_fx(u["pair"], min(float(eff["daily_usd"]) * 0.4, cap), 1, sim_hour=h, dt=-60 + i) for i in range(4)]
        elif sid == "FX-10":
            S = [dict(pre=("balance", 5_000_000), **_fx(u["pair"], u["amt"], lev_ok, sim_hour=h))]
            note = "Số dư demo bị hạ về 5.000.000 VND (dùng nút 'Nạp số dư demo' để khôi phục)."
        elif sid == "FX-11": S = [_fx(u["pair"], u["amt"], 1, sim_hour=h)]
    else:
        tcap = float(eff["transfer_per_txn"])
        tok = _card(cid)
        mer, mcc, ctry = u["mer"]
        if sid == "PAY-01": S = [_t(u["tamt"], u["ben"], sim_hour=h)]
        elif sid == "PAY-02": S = [_c("ONLINE_PURCHASE", u["camt"], tok, mer, mcc, ctry or "VN", True, sim_hour=h)]
        elif sid == "PAY-03": S = [_t(tcap * 1.2, u["ben"], sim_hour=h)]
        elif sid == "PAY-04":
            amt = min(u["tamt"] * 2, tcap)
            S = [dict(pre=("balance", amt * 0.4), **_t(amt, u["ben"], sim_hour=h))]
            note = "Số dư demo bị hạ để thấp hơn số tiền chuyển."
        elif sid == "PAY-05": S = [_t(min(float(eff["new_beneficiary_kya_above"]) * 1.5 + 1_000_000, tcap), "88800" + str(store.now())[-5:], sim_hour=h)]
        elif sid in ("PAY-06", "PAY-07"): S = [_t(u["tamt"], u["ben"], sim_hour=h)]; note = "Chỉ cho KQ KYA khi chạy đúng khách đề xuất."
        elif sid == "PAY-08":
            r = _c("ONLINE_PURCHASE", 1_500_000, tok, mer, mcc, ctry or "VN", True, sim_hour=h)
            r["raw"]["card_number"] = TEST_PAN
            S = [r]
        elif sid == "PAY-09":
            r = _c("ONLINE_PURCHASE", 1_500_000, tok, mer, mcc, ctry or "VN", True, sim_hour=h)
            r["raw"]["cvv"] = "123"
            S = [r]
        elif sid == "PAY-10": S = [_c("ONLINE_PURCHASE", 900_000, tok, "MCASINO", "7995", "VN", True, sim_hour=h)]
        elif sid == "PAY-11": S = [_c("ONLINE_PURCHASE", 12_000_000, tok, "MX77", "5967", "NG", False, sim_hour=h)]
        elif sid == "PAY-12": S = [_c("ONLINE_PURCHASE", 5000, tok, f"MT{i}", "5732", "US", False, sim_hour=h, dt=-200 + i * 15) for i in range(8)]
        elif sid == "PAY-13": S = [_t(tcap * 0.95, u["ben"], sim_hour=h, dt=-120 + i * 30) for i in range(3)]
        elif sid == "PAY-14":
            amt = min(u["tamt"] * 3, tcap)
            S = [dict(pre=("balance", amt / 0.85), **_t(amt, u["ben"], sim_hour=h))]
            note = "Số dư demo được đặt để giao dịch chiếm ≈85%."
        elif sid == "PAY-15": S = [_t(u["tamt"], u["ben"], sim_hour=h)]
        elif sid == "PAY-16": S = [_c("ONLINE_PURCHASE", 1_000_000, "tok_fake", mer, mcc, ctry or "VN", True, sim_hour=h)]
    return ag, S, note


def prepare(cid):
    """Cô lập kịch bản: lưu trữ kết quả lab cũ (không tính vào hạn mức/velocity/baseline), hủy KYA/REVIEW lab đang chờ,
    xóa cờ theo dõi và đưa số dư về mức demo mặc định để kết quả lặp lại được."""
    t = store.now()
    db.execute("UPDATE kya SET status='EXPIRED', decided_at=? WHERE status='PENDING' AND action_id IN "
               "(SELECT id FROM actions WHERE customer_id=? AND source='LAB')", (t, cid))
    db.execute("UPDATE actions SET status='EXPIRED', reason_public='Bị hủy do chạy kịch bản Lab mới' "
               "WHERE customer_id=? AND source='LAB' AND status IN ('PENDING_KYA','REVIEW_PENDING')", (cid,))
    db.execute("UPDATE actions SET sim=2 WHERE customer_id=? AND source='LAB'", (cid,))
    db.execute("INSERT INTO flags(customer_id,suspicion,watchlist,updated_at) VALUES(?,0,0,?) ON CONFLICT(customer_id) "
               "DO UPDATE SET suspicion=0, watchlist=0, updated_at=excluded.updated_at", (cid, t))
    from agentmon.seed import PROFILES
    base = (PROFILES.get(cid) or {}).get("balance", 100_000_000)
    bal, avail = engine.available_balance(cid)
    if bal < base:
        _set_balance(cid, base)


def run(sid, cid, ip=""):
    if sid not in {s[0] for s in SCEN}:
        return {"error": "Kịch bản không tồn tại"}
    prepare(cid)
    ag, steps, note = build(sid, cid)
    if not steps:
        return {"error": note or "Không dựng được kịch bản"}
    out = []
    now = store.now()
    for st in steps:
        if st.get("pre"):
            _set_balance(cid, st["pre"][1])
        r = engine.evaluate(st["raw"], ag, source="LAB", customer_hint=cid, sim_hour=st.get("sim_hour"),
                            sim_ts=(now + st["dt"]) if st.get("dt") is not None else None, ip=ip)
        out.append({"action_id": r["action_id"], "decision": r["decision"], "status": r["status"], "risk": r.get("final_risk"),
                    "anomaly": r.get("anomaly"), "behavior": r.get("behavior"), "velocity": r.get("velocity"),
                    "reason": r.get("hard_reason") or "; ".join(r.get("reasons") or []) or r["reason_public"],
                    "triggers": [t[1] for t in r.get("triggers") or []], "kya_id": r.get("kya_id"), "llm": r.get("llm"),
                    "request": {k: v for k, v in st["raw"].items() if k not in ("card_number", "cvv", "card_token")}})
    return {"scenario": sid, "agent_id": ag, "customer_id": cid, "note": note, "steps": out}


def topup(cid, amount):
    _set_balance(cid, float(amount))
