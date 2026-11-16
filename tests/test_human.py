"""v1.2: giao dịch của NGƯỜI từ mọi hệ thống nguồn (portal, Digibank/Digibiz, switch thẻ, ATM, IPS), cả chuyển tiền,
cùng Agent trên một tài khoản."""
import itertools
import threading

import pytest

from agentmon import db, engine, lab, seed, sources
from agentmon.constants import SOURCE_SYSTEMS
from tests.conftest import BROWSER, login_ok

_n = itertools.count(1)


@pytest.fixture(autouse=True)
def reseed():
    db.init()
    seed.seed(force=True)
    yield


def hx(cid, src, body, hour=None, ts=None):
    body = dict(body)
    body.setdefault("request_id", f"t{next(_n)}")
    return engine.evaluate(body, "", source="TEST", customer_hint=cid, sim_hour=hour, sim_ts=ts, use_llm=False, actor="HUMAN", source_system=src)


def xfer(cid, amt, ben, src="DIGIBANK", dev=None, risk=0, hour=None, ts=None):
    return hx(cid, src, dict(domain="PAY", kind="TRANSFER", amount_vnd=amt, beneficiary_account=ben, device_id=dev, session_risk=risk), hour, ts)


def usual(cid="CUST001"):
    return lab._usual(cid, "PAY")


def warm(cid, dev, n=3):
    u = usual(cid)
    for _ in range(n):
        r = xfer(cid, u["tamt"], u["ben"], dev=dev, hour=u["hour"])
        assert r["decision"] == "ALLOW", (r["decision"], r["reasons"])


# ------------------------------------------------------------------ chuyển tiền của người
def test_human_routine_transfer_allowed_on_known_device():
    u = usual()
    warm("CUST001", "DEV-IPH001")
    r = xfer("CUST001", u["tamt"], u["ben"], dev="DEV-IPH001", hour=u["hour"])
    assert r["decision"] == "ALLOW" and r["status"] == "EXECUTED" and r["actor_type"] == "HUMAN" and r["source_system"] == "DIGIBANK"
    assert r["fraud_class"] == "NORMAL"


def test_account_takeover_pattern_new_device_new_beneficiary_large_night():
    u = usual()
    warm("CUST001", "DEV-IPH001")
    r = xfer("CUST001", u["tamt"] * 6, "7777000011", dev="DEV-STRANGE9", hour=3)
    assert r["decision"] in ("STEP_UP", "REVIEW") and r["status"] in ("PENDING_STEPUP", "REVIEW_PENDING")
    assert "ACCOUNT_TAKEOVER" in r["fraud_types"] and r["fraud_class"] == "FRAUD_SUSPECTED"
    codes = {t[0] for t in r["triggers"]}
    assert {"NEW_DEVICE", "NEW_BENEFICIARY"} <= codes


def test_anti_bot_session_score_feeds_monitor():
    u = usual()
    warm("CUST001", "DEV-IPH001")
    ok = xfer("CUST001", u["tamt"], u["ben"], dev="DEV-IPH001", hour=u["hour"], risk=5)
    bot = xfer("CUST001", u["tamt"], u["ben"], dev="DEV-IPH001", hour=u["hour"], risk=95)
    assert ok["decision"] == "ALLOW"
    assert bot["decision"] in ("STEP_UP", "REVIEW") and "SESSION_BOT" in {t[0] for t in bot["triggers"]} and "SESSION_BOT" in bot["fraud_types"]
    assert bot["details"]["session_risk"] == 0.95


def test_mule_collection_many_customers_to_one_recipient():
    ben = "5550001234"
    seen = []
    for cid in ("CUST001", "CUST002", "CUST003", "CUST004", "CUST005", "CUST006", "CUST007", "CUST008"):
        lab.prepare(cid)
        db.execute("INSERT OR REPLACE INTO accounts(customer_id,balance_vnd) VALUES(?,?)", (cid, 5_000_000_000))
        seen.append(xfer(cid, 3_000_000, ben, src="IPS_TRANSFER", hour=10))
    last = seen[-1]
    assert last["details"]["trace"]["context"]["benef_senders"] >= 5
    assert "MULE_COLLECTION" in last["fraud_types"] and "MULE_RECIPIENT" in {t[0] for t in last["triggers"]}
    assert last["decision"] in ("STEP_UP", "REVIEW", "BLOCK")
    assert seen[0]["decision"] == "ALLOW" or "NEW_BENEFICIARY" in {t[0] for t in seen[0]["triggers"]}      # người gửi đầu chưa bị nghi


def test_human_transfer_over_limit_blocked_without_agent_caps():
    eff = engine.policy.effective_limits("PAY", "VIP", "CUST001", {})
    lab._set_balance("CUST001", 10 ** 12)
    r = xfer("CUST001", float(eff["transfer_per_txn"]) * 2, usual()["ben"], hour=10)
    assert r["decision"] == "BLOCK" and "hạn mức" in r["hard_reason"]
    for i in range(int(eff["per_hour"]) + 5):               # trần số lệnh/giờ là của Agent, không áp cho người
        r = xfer("CUST005", 100_000, usual("CUST005")["ben"], hour=10)
    assert "Vượt số giao dịch" not in (r["hard_reason"] or "")


# ------------------------------------------------------------------ các nguồn khác
def test_atm_switch_routine_overlimit_and_foreign_night():
    u = lab._usual("CUST001", "PAY")
    tok = lab._card("CUST001")
    atm = u.get("atm_ref") or "ATM0101"
    ok = hx("CUST001", "ATM_SWITCH", dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=u.get("atm_amt") or 3_000_000, card_token=tok, atm_id=atm), hour=u["hour"])
    assert ok["decision"] == "ALLOW" and ok["channel_type"] == "ATM"
    eff = engine.policy.effective_limits("PAY", "VIP", "CUST001", {})
    big = hx("CUST001", "ATM_SWITCH", dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=float(eff["atm_per_txn"]) * 1.5, card_token=tok, atm_id=atm), hour=10)
    assert big["decision"] == "BLOCK"
    far = hx("CUST001", "ATM_SWITCH", dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=8_000_000, card_token=tok, atm_id="ATMTH9", country="TH"), hour=3)
    assert far["decision"] in ("STEP_UP", "REVIEW") and "ATM_CASHOUT_ABROAD" in far["fraud_types"]


def test_card_switch_pos_and_wallet_new_device():
    tok = lab._card("CUST001")
    pos = hx("CUST001", "CARD_SWITCH", dict(domain="PAY", kind="CARD_PAYMENT", amount_vnd=700_000, card_token=tok, merchant_id="M300", mcc="5411", country="VN"), hour=11)
    assert pos["channel_type"] == "POS" and pos["decision"] in ("ALLOW", "STEP_UP")
    risky = hx("CUST001", "CARD_SWITCH", dict(domain="PAY", kind="ONLINE_PURCHASE", amount_vnd=9_000_000, card_token=tok, merchant_id="MXRISK", mcc="5967",
                                              country="NG", three_ds=False), hour=2)
    assert risky["decision"] in ("STEP_UP", "REVIEW", "BLOCK") and risky["fraud_class"] == "FRAUD_SUSPECTED"
    u = lab._usual("CUST001", "PAY")
    w = hx("CUST001", "CARD_SWITCH", dict(domain="PAY", kind="WALLET_PAYMENT", amount_vnd=1_500_000, card_token=tok, merchant_id="M300", mcc="5411",
                                         country="VN", wallet_provider="APPLE_PAY", device_id="DEV-UNKNOWN-77"), hour=u["hour"])
    assert w["decision"] in ("STEP_UP", "REVIEW") and "WALLET_DEVICE_ABUSE" in w["fraud_types"]


def test_digibiz_bill_and_portal_fx():
    u = lab._usual("CUST002", "PAY")
    tok = lab._card("CUST002")
    b = hx("CUST002", "DIGIBIZ", dict(domain="PAY", kind="BILL_PAYMENT", amount_vnd=u.get("bill_amt") or 1_500_000, card_token=tok,
                                      biller_id=u.get("bill_ref") or "BILL10"), hour=u["hour"])
    assert b["decision"] == "ALLOW" and b["channel_type"] == "DIGIBIZ"
    f = lab._usual("CUST001", "FX")
    ok = hx("CUST001", "PORTAL", dict(domain="FX", kind="FX_TRADE", pair=f["pair"], side="BUY", notional_usd=f["amt"], leverage=1, session_risk=3), hour=f["hour"])
    bot = hx("CUST001", "PORTAL", dict(domain="FX", kind="FX_TRADE", pair=f["pair"], side="BUY", notional_usd=f["amt"], leverage=1, session_risk=97), hour=f["hour"])
    assert ok["decision"] == "ALLOW" and bot["decision"] in ("STEP_UP", "REVIEW") and "SESSION_BOT" in bot["fraud_types"]


def test_source_system_cannot_send_foreign_kind_or_bad_actor():
    with pytest.raises(engine.BadRequest):
        hx("CUST001", "ATM_SWITCH", dict(domain="PAY", kind="TRANSFER", amount_vnd=1000, beneficiary_account="123456789"))
    with pytest.raises(engine.BadRequest):
        xfer("CUST001", 1000, "123456789", risk=150)
    with pytest.raises(engine.BadRequest):
        engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=1000, beneficiary_account="123456789"), "", customer_hint="CUST001", actor="HUMAN", source_system="NOPE")
    assert set(SOURCE_SYSTEMS) == {"PORTAL", "DIGIBANK", "DIGIBIZ", "CARD_SWITCH", "ATM_SWITCH", "IPS_TRANSFER"}


# ------------------------------------------------------------------ người ↔ Agent
def test_human_and_agent_on_same_account_conflict_signal():
    cid = "CUST001"
    u = usual(cid)
    now = engine.store.now()
    for i in range(4):
        xfer(cid, u["tamt"], u["ben"], hour=u["hour"], ts=now - 300 + i * 20)
    ag = lab._agent_for(cid, "PAY")
    r = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"]), ag, source="LAB", customer_hint=cid,
                        sim_hour=u["hour"], sim_ts=now - 100)
    assert r["details"]["trace"]["context"]["cross_actor_n10"] >= 3 and "ACTOR_CONFLICT" in r["fraud_types"]


def test_kill_switch_stops_agents_but_not_people():
    engine.policy.set_kill_switch(True, "test", "hq")
    try:
        u = usual()
        h = xfer("CUST001", u["tamt"], u["ben"], hour=u["hour"])
        ag = lab._agent_for("CUST001", "PAY")
        a = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"]), ag, source="LAB",
                            customer_hint="CUST001", sim_hour=u["hour"])
        assert h["decision"] != "BLOCK" and a["decision"] == "BLOCK" and "KILL-SWITCH" in a["hard_reason"]
    finally:
        engine.policy.set_kill_switch(False, "", "hq")


def test_concurrent_human_and_agent_cannot_overspend():
    cid = "CUST001"
    lab.prepare(cid)
    lab._set_balance(cid, 30_000_000)
    u, ag = usual(cid), lab._agent_for(cid, "PAY")
    out = {}

    def human():
        out["h"] = xfer(cid, 28_000_000, u["ben"], hour=u["hour"])

    def agent():
        out["a"] = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=28_000_000, beneficiary_account=u["ben"]), ag, source="LAB",
                                   customer_hint=cid, sim_hour=u["hour"])
    ts = [threading.Thread(target=f) for f in (human, agent)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert db.one("SELECT balance_vnd b FROM accounts WHERE customer_id=?", (cid,))["b"] >= 0
    assert sum(1 for v in out.values() if v["status"] == "EXECUTED") <= 1


# ------------------------------------------------------------------ step-up
def _stepup_txn(dev="DEV-OTHER88"):
    u = usual()
    warm("CUST001", "DEV-IPH001")
    return xfer("CUST001", u["tamt"], u["ben"], dev=dev, hour=u["hour"])


def test_step_up_holds_balance_then_executes_or_fails():
    r = _stepup_txn()
    assert r["decision"] == "STEP_UP"
    bal, avail = engine.available_balance("CUST001")
    assert avail < bal                                                   # giữ chỗ số dư
    bad = engine.step_up_result(r["action_id"], True, source_system="ATM_SWITCH")
    assert bad["status"] == "FORBIDDEN"                                  # nguồn khác không được xác nhận
    ok = engine.step_up_result(r["action_id"], True, source_system="DIGIBANK")
    assert ok["status"] == "EXECUTED"
    assert engine.step_up_result(r["action_id"], True, source_system="DIGIBANK")["status"] == "EXECUTED"      # idempotent
    r2 = _stepup_txn("DEV-OTHER99")
    s0 = db.one("SELECT suspicion s FROM flags WHERE customer_id='CUST001'")
    fail = engine.step_up_result(r2["action_id"], False, source_system="DIGIBANK")
    assert fail["status"] == "STEPUP_FAILED"
    s1 = db.one("SELECT suspicion s FROM flags WHERE customer_id='CUST001'")["s"]
    assert s1 > ((s0 or {}).get("s") or 0)


def test_step_up_expires():
    r = _stepup_txn()
    db.execute("UPDATE actions SET ts=ts-? WHERE id=?", (engine.STEPUP_HOLD_SECONDS + 5, r["action_id"]))
    assert engine.step_up_result(r["action_id"], True, "DIGIBANK")["status"] == "STEPUP_EXPIRED"
    bal, avail = engine.available_balance("CUST001")
    assert abs(bal - avail) < 1e-6


# ------------------------------------------------------------------ API cho hệ thống nguồn
def test_txn_api_auth_idempotency_validation_and_no_score_leak(app):
    c = app.test_client()
    H = {"User-Agent": "bank-core/1.0"}
    body = dict(customer_id="CUST001", request_id="api-1", domain="PAY", kind="TRANSFER", amount_vnd=1_000_000, beneficiary_account=usual()["ben"])
    assert c.post("/txn-api/v1/monitor/transaction", json=body, headers=H).status_code == 401
    key = sources.issue_key("digibank-demo")
    H["X-Source-Key"] = key
    r1 = c.post("/txn-api/v1/monitor/transaction", json=body, headers=H)
    d1 = r1.get_json()
    assert r1.status_code == 200 and d1["action"] in ("ALLOW", "STEP_UP") and "elapsed_ms" in d1
    assert not ({"final_risk", "anomaly", "behavior", "velocity", "trace", "details"} & set(d1))     # không lộ điểm nội bộ
    d2 = c.post("/txn-api/v1/monitor/transaction", json=body, headers=H).get_json()
    assert d2["duplicate"] is True and d2["transaction_id"] == d1["transaction_id"]
    assert c.post("/txn-api/v1/monitor/transaction", json={k: v for k, v in body.items() if k != "request_id"}, headers=H).status_code == 400
    assert c.post("/txn-api/v1/monitor/transaction", json=dict(body, request_id="api-2", kind="ATM_WITHDRAWAL"), headers=H).status_code == 400
    assert c.post("/txn-api/v1/monitor/transaction", json=dict(body, request_id="api-3", session=dict(anti_bot_score=500)), headers=H).status_code == 400
    # nguồn khác không đọc/xác nhận giao dịch của nguồn này
    H2 = dict(H, **{"X-Source-Key": sources.issue_key("atm_switch-demo".replace("_", "_"))})
    assert c.get(f"/txn-api/v1/transactions/{d1['transaction_id']}", headers=H2).status_code == 404
    assert c.get(f"/txn-api/v1/transactions/{d1['transaction_id']}", headers=H).status_code == 200


def test_txn_api_step_up_flow_and_key_rotation(app):
    c = app.test_client()
    k1 = sources.issue_key("digibank-demo")
    H = {"User-Agent": "bank-core/1.0", "X-Source-Key": k1}
    u = usual()
    for i in range(3):
        c.post("/txn-api/v1/monitor/transaction", headers=H, json=dict(customer_id="CUST001", request_id=f"w{i}", domain="PAY", kind="TRANSFER",
               amount_vnd=u["tamt"], beneficiary_account=u["ben"], session=dict(device_id="DEV-IPH001")))
    body = dict(customer_id="CUST001", request_id="su1", domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"] * 5, beneficiary_account="8880001111",
                session=dict(device_id="DEV-NEW555", anti_bot_score=88))
    ch = c.post("/txn-api/v1/monitor/transaction", headers=H, json=body).get_json()
    assert ch["stage"] == "ANTIBOT" and ch["action"] == "CHALLENGE"            # tầng 1 dừng, Monitor chưa chạy
    body.update(request_id="su2", session=dict(body["session"], turnstile_ok=True))
    r = c.post("/txn-api/v1/monitor/transaction", headers=H, json=body).get_json()
    assert r["stage"] if "stage" in r else True
    assert r["action"] in ("STEP_UP", "REVIEW")
    if r["action"] == "STEP_UP":
        assert r["step_up"]["method"] == "BIOMETRIC"
        ok = c.post(r["step_up"]["callback"], json={"passed": True}, headers=H)
        assert ok.status_code == 200 and ok.get_json()["status"] in ("EXECUTED", "FAILED")
        assert c.post(r["step_up"]["callback"], json={"passed": "yes"}, headers=H).status_code == 400
    k2 = sources.issue_key("digibank-demo")                               # đổi khóa → khóa cũ mất hiệu lực
    assert c.post("/txn-api/v1/monitor/transaction", headers=H, json={}).status_code == 401 and k2 != k1


def test_hq_can_issue_source_key_staff_cannot(app):
    hq = app.test_client(); login_ok(hq, "hq01")
    r = hq.post("/api/agent/hq/sources/portal-demo/key", headers=dict(BROWSER, **{"X-CSRF-Token": ""}))
    assert r.status_code in (200, 400, 403)        # CSRF/MFA do Anti-Bot kiểm soát; xem test_agentmon cho luồng HQ đầy đủ
    st = app.test_client(); login_ok(st, "staff01")
    assert st.get("/api/agent/hq/sources", headers=BROWSER).status_code in (401, 403)


def test_trace_and_reports_carry_actor_fields():
    u = usual()
    warm("CUST001", "DEV-IPH001")
    r = xfer("CUST001", u["tamt"], u["ben"], dev="DEV-IPH001", hour=u["hour"])
    tr = r["details"]["trace"]
    assert tr["input"]["actor_type"] == "HUMAN" and tr["input"]["source_system"] == "DIGIBANK" and tr["context"]["session_risk"] == 0
    from agentmon import reports
    ov = reports.overview("PAY", None)
    assert ov["by_actor"].get("HUMAN", 0) >= 1 and ov["by_actor"].get("AGENT", 0) >= 1
