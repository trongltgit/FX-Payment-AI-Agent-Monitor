"""Dữ liệu demo: số dư, thẻ Visa/Mastercard (số TEST), Authenticator, Agent, lịch sử giao dịch 90–200 ngày + vài sự cố mẫu."""
import random
import secrets
import time

from agentmon import cards, db, kya
from utils import store

TEST_CARDS = {
    "CUST001": [("4111111111111111", "NGUYEN VAN A", 12, 2029, 50_000_000, 150_000_000, 1, 1),
                ("5555555555554444", "NGUYEN VAN A", 6, 2028, 30_000_000, 100_000_000, 1, 0)],
    "CUST002": [("4012888888881881", "CONG TY ABC", 3, 2030, 300_000_000, 1_000_000_000, 1, 1),
                ("5105105105105100", "CONG TY ABC", 9, 2029, 200_000_000, 800_000_000, 1, 1)],
    "CUST003": [("4222222222222", "TRAN THI B", 11, 2028, 15_000_000, 40_000_000, 1, 0)],
    "CUST004": [("2223003122003222", "LE VAN C", 8, 2029, 20_000_000, 60_000_000, 1, 0)],
    "CUST005": [("4000056655665556", "PHAM THI D", 1, 2030, 100_000_000, 300_000_000, 1, 1)],
}
PROFILES = {
    "CUST001": dict(fx=dict(n=70, mean=18000, lev=(1, 6), pairs=["USDVND", "EURVND", "USDJPY"], hours=(9, 17)),
                    pay=dict(n=90, tmean=18e6, benef=6, cmean=3.5e6, merch=8, countries=["VN", "VN", "VN", "SG"], hours=(8, 21)),
                    days=(1.6, 90), ch="AGENT", balance=2_500e6),
    "CUST002": dict(fx=dict(n=90, mean=140000, lev=(1, 3), pairs=["USDVND", "EURVND", "GBPVND"], hours=(8, 17)),
                    pay=dict(n=120, tmean=900e6, benef=9, cmean=25e6, merch=10, countries=["VN"], hours=(8, 17)),
                    days=(1.6, 90), ch="AGENT", balance=25_000e6),
    "CUST003": dict(fx=None, pay=dict(n=30, tmean=6e6, benef=3, cmean=1.2e6, merch=5, countries=["VN"], hours=(9, 20)),
                    days=(110, 200), ch="ONLINE", balance=45e6),
    "CUST004": dict(fx=None, pay=dict(n=25, tmean=8e6, benef=4, cmean=0, merch=0, countries=["VN"], hours=(8, 16)),
                    days=(5, 120), ch="OFFLINE", balance=90e6),
    "CUST005": dict(fx=dict(n=140, mean=30000, lev=(2, 10), pairs=["USDVND", "EURUSD", "GBPUSD", "USDJPY", "AUDUSD"], hours=(8, 23)),
                    pay=dict(n=40, tmean=25e6, benef=5, cmean=4e6, merch=6, countries=["VN", "SG", "US"], hours=(8, 22)),
                    days=(1.6, 90), ch="AGENT", balance=5_000e6),
}
AGENTS = [
    ("agent-fx-001", "CUST001", "Robot FX Alpha (cá nhân)", ["FX"], "ACTIVE", {"FX": {"per_order_usd": 60000, "daily_usd": 200000}}, 0),
    ("agent-pay-001", "CUST001", "Trợ lý thanh toán hóa đơn", ["PAY"], "ACTIVE", {"PAY": {"transfer_per_txn": 200_000_000}}, 0),
    ("agent-corp-002", "CUST002", "Treasury Bot – Cty ABC", ["FX", "PAY"], "ACTIVE", {}, 0),
    ("agent-pay-003", "CUST003", "Agent thanh toán gia đình", ["PAY"], "ACTIVE", {}, 0),
    ("agent-pay-004", "CUST004", "Agent mua sắm online", ["PAY"], "PENDING", {}, 3),
    ("agent-fx-005", "CUST005", "Quant Bot Beta", ["FX", "PAY"], "ACTIVE", {}, 0),
]


def _hist(rng, cid, p, now):
    rows = []
    a0, a1 = p["days"]
    benef = [str(rng.randint(10**9, 10**10 - 1)) for _ in range(p["pay"]["benef"])] if p.get("pay") else []
    merch = [f"M{rng.randint(100, 999)}" for _ in range(p["pay"]["merch"])] if p.get("pay") else []
    card = db.one("SELECT card_id FROM cards WHERE customer_id=? LIMIT 1", (cid,))
    from app.customer.mock_db import get_demo_customer
    br = get_demo_customer(cid)["branch_id"]

    def ts_in(h0, h1):
        d = rng.uniform(a0, a1)
        t = now - d * 86400
        base = (int((t + 25200) // 86400)) * 86400 - 25200
        return base + rng.randint(h0, h1) * 3600 + rng.randint(0, 3599)

    if p.get("fx"):
        f = p["fx"]
        for _ in range(f["n"]):
            usd = max(500, f["mean"] * rng.lognormvariate(0, 0.4))
            lev = round(rng.uniform(*f["lev"]), 1)
            rows.append(dict(ts=ts_in(*f["hours"]), domain="FX", kind="FX_TRADE", amount_usd=round(usd, 2),
                             amount_vnd=round(usd * 26200), pair=rng.choice(f["pairs"]), side=rng.choice(["BUY", "SELL"]),
                             leverage=lev, channel=p["ch"], risk=rng.uniform(0.03, 0.22)))
    q = p["pay"]
    for _ in range(q["n"]):
        k = rng.choices(["TRANSFER", "ONLINE_PURCHASE", "CARD_PAYMENT"], [0.5, 0.3, 0.2] if q["cmean"] else [1, 0, 0])[0]
        if k == "TRANSFER":
            amt = max(50_000, q["tmean"] * rng.lognormvariate(0, 0.5))
            rows.append(dict(ts=ts_in(*q["hours"]), domain="PAY", kind=k, amount_vnd=round(amt, -3), beneficiary=rng.choice(benef),
                             channel=p["ch"], risk=rng.uniform(0.03, 0.2)))
        else:
            amt = max(20_000, q["cmean"] * rng.lognormvariate(0, 0.6))
            rows.append(dict(ts=ts_in(*q["hours"]), domain="PAY", kind=k, amount_vnd=round(amt, -3), merchant=rng.choice(merch),
                             mcc=rng.choice(["5411", "5812", "5311", "4121", "5732", "4900"]), country=rng.choice(q["countries"]),
                             card_id=card["card_id"] if card else None, channel=p["ch"], risk=rng.uniform(0.03, 0.2)))
    for r in rows:
        r.setdefault("beneficiary", None); r.setdefault("merchant", None); r.setdefault("mcc", None)
        r.setdefault("country", None); r.setdefault("card_id", None); r.setdefault("pair", None); r.setdefault("side", None)
        r.setdefault("leverage", None); r.setdefault("amount_usd", None)
    return rows, br


def seed(force=False):
    if db.meta_get("seeded") and not force:
        return False
    from app.customer.mock_db import get_demo_customer
    db.init()
    with db.tx() as c:
        for t in ("accounts", "cards", "trusted_beneficiaries", "agents", "authenticators", "actions", "kya", "limits", "flags", "policies"):
            c.execute(f"DELETE FROM {t}")
    rng = random.Random(20260105)
    now = store.now()
    for cid, p in PROFILES.items():
        db.execute("INSERT INTO accounts(customer_id,balance_vnd) VALUES(?,?)", (cid, p["balance"]))
        for (pan, holder, em, ey, pt, dl, cnp, intl) in TEST_CARDS.get(cid, []):
            ok, msg, _ = cards.add_card(cid, pan, holder, em, ey, pt, dl, bool(cnp), bool(intl))
            assert ok, (cid, pan, msg)
        rows, br = _hist(rng, cid, p, now)
        with db.tx() as c:
            for r in rows:
                c.execute("INSERT INTO actions(ts,domain,kind,customer_id,branch_id,agent_id,channel,amount_vnd,amount_usd,pair,side,leverage,"
                          "beneficiary,merchant,mcc,country,card_id,hour,details,final_risk,decision,status,reasons,triggers,reason_public,source,sim) "
                          "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (r["ts"], r["domain"], r["kind"], cid, br, "history", r["channel"], r["amount_vnd"], r["amount_usd"], r["pair"],
                           r["side"], r["leverage"], r["beneficiary"], r["merchant"], r["mcc"], r["country"], r["card_id"],
                           int(((r["ts"] + 25200) // 3600) % 24), "{}", round(r["risk"], 3), "ALLOW", "EXECUTED", "[]", "[]",
                           "Giao dịch lịch sử (dữ liệu mẫu)", "SEED", 0))
    for cid in ("CUST001", "CUST002", "CUST003", "CUST005"):
        db.execute("INSERT INTO authenticators(customer_id,totp_secret,created_at) VALUES(?,?,?)", (cid, kya.new_secret(), now))
    for (aid, cid, name, doms, st, lim, prob) in AGENTS:
        cust = get_demo_customer(cid)
        kinds = (["FX_TRADE"] if "FX" in doms else []) + (["TRANSFER", "ONLINE_PURCHASE", "CARD_PAYMENT"] if "PAY" in doms else [])
        t = now - 30 * 86400
        db.execute("INSERT INTO agents(agent_id,customer_id,branch_id,name,purpose,domains,kinds,status,limits,requested_limits,consent_version,"
                   "consent_at,consent_ip,consent_hash,requested_at,approved_by,approved_at,valid_until,probation_left,is_demo,created_at) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (aid, cid, cust["branch_id"], name, "Dữ liệu demo", db.jdump(doms), db.jdump(kinds), st, db.jdump(lim), "{}", "2026-01",
                    t, "127.0.0.1", "seed", t, "admin_cn01" if st == "ACTIVE" else None, t if st == "ACTIVE" else None,
                    (now + 335 * 86400) if st == "ACTIVE" else None, prob, 1, t))
    # beneficiary tin cậy
    for cid in ("CUST001", "CUST002"):
        r = db.one("SELECT beneficiary FROM actions WHERE customer_id=? AND beneficiary IS NOT NULL LIMIT 1", (cid,))
        if r:
            db.execute("INSERT INTO trusted_beneficiaries(customer_id,account,bank,added_at) VALUES(?,?,?,?)", (cid, r["beneficiary"], "VCB", now))
    _incidents(rng, now)
    db.meta_set("seeded", {"at": int(now), "version": 2})
    return True


def _incidents(rng, now):
    """Sự cố mẫu để dashboard/hàng chờ duyệt có dữ liệu ngay."""
    samples = [
        ("CUST001", "agent-fx-001", "FX", "FX_TRADE", dict(amount_usd=250000, amount_vnd=250000 * 26200, pair="USDVND", side="BUY", leverage=5),
         "BLOCK", "BLOCKED", 1.0, "Giá trị lệnh 250,000 USD vượt hạn mức/lệnh 60,000 USD", 6.2),
        ("CUST002", "agent-corp-002", "PAY", "TRANSFER", dict(amount_vnd=3_000_000_000, beneficiary="7771234567"),
         "REVIEW", "REVIEW_PENDING", 0.66, "ML bất thường 0.71; Người thụ hưởng mới; Giá trị gấp 3.3 lần mức trung bình", 0.2),
        ("CUST005", "agent-fx-005", "FX", "FX_TRADE", dict(amount_usd=95000, amount_vnd=95000 * 26200, pair="GBPUSD", side="SELL", leverage=18),
         "REVIEW", "REVIEW_PENDING", 0.63, "Đòn bẩy 18x cao hơn nhiều thói quen; Giao dịch lớn ngoài giờ", 0.4),
        ("CUST001", "agent-pay-001", "PAY", "CARD_PAYMENT", dict(amount_vnd=18_000_000, merchant="MX77", mcc="5967", country="NG"),
         "KYA", "DENIED_BY_CUSTOMER", 0.52, "Quốc gia rủi ro cao (NG); Ngành hàng rủi ro cao", 3.1),
        ("CUST005", "agent-pay-005", "PAY", "TRANSFER", dict(amount_vnd=60_000_000, beneficiary="5559998881"),
         "KYA", "EXECUTED", 0.41, "Người thụ hưởng mới vượt ngưỡng", 4.4),
        ("CUST003", "agent-pay-003", "PAY", "CARD_PAYMENT", dict(amount_vnd=2000, merchant="MT1", mcc="5732", country="US"),
         "BLOCK", "BLOCKED", 1.0, "Thẻ chưa bật giao dịch quốc tế", 8.0),
        ("CUST002", "agent-corp-002", "FX", "FX_TRADE", dict(amount_usd=210000, amount_vnd=210000 * 26200, pair="EURVND", side="BUY", leverage=2),
         "KYA", "EXPIRED", 0.38, "Giá trị 210,000 USD ≥ ngưỡng bắt buộc xác minh", 9.5),
    ]
    from app.customer.mock_db import get_demo_customer
    for (cid, ag, dom, kind, f, dec, st, risk, why, days) in samples:
        br = get_demo_customer(cid)["branch_id"]
        t = now - days * 86400 if days > 1 else now - days * 3600
        db.execute("INSERT INTO actions(ts,domain,kind,customer_id,branch_id,agent_id,channel,amount_vnd,amount_usd,pair,side,leverage,beneficiary,"
                   "merchant,mcc,country,hour,details,anomaly,behavior,velocity,final_risk,decision,status,hard_reason,reasons,triggers,reason_public,llm,source,sim) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (t, dom, kind, cid, br, ag, "AGENT", f.get("amount_vnd"), f.get("amount_usd"), f.get("pair"), f.get("side"), f.get("leverage"),
                    f.get("beneficiary"), f.get("merchant"), f.get("mcc"), f.get("country"), int(((t + 25200) // 3600) % 24), "{}",
                    0.7 if dec != "BLOCK" else None, 0.5 if dec != "BLOCK" else None, 0.2 if dec != "BLOCK" else None, risk, dec, st,
                    why if dec == "BLOCK" else None, db.jdump([why]), "[]", "Sự cố mẫu", None, "SEED", 0))
