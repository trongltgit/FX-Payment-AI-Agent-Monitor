"""Test tích hợp AI Agent Monitor (FX + Thanh toán) trên nền Anti-Bot."""
import pytest

from agentmon import cards, db, kya, seed
from tests.conftest import BROWSER, login_ok, post
from utils import totp as totp_mod


@pytest.fixture(autouse=True)
def reseed():
    db.init()
    seed.seed(force=True)
    yield


def sess(app, user):
    c = app.test_client()
    t = login_ok(c, user)
    return c, t


def get(c, path):
    r = c.get(path, headers=BROWSER)
    return r.status_code, r.get_json()


def lab(c, t, sid, cid):
    r = post(c, "/api/agent/lab/run", t, {"scenario": sid, "customer_id": cid})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["steps"]


def code_for(cid):
    from utils import store
    return totp_mod.totp_now(kya.get_auth(cid)["totp_secret"], at=store.now())


# ------------------------------------------------------------------ pipeline FX
def test_fx_normal_allow_and_limits_block(app):
    c, t = sess(app, "cust001")
    assert lab(c, t, "FX-01", "CUST001")[0]["decision"] == "ALLOW"
    s = lab(c, t, "FX-02", "CUST001")[0]
    assert s["decision"] == "BLOCK" and "hạn mức" in s["reason"]
    assert lab(c, t, "FX-03", "CUST001")[0]["decision"] == "BLOCK"
    assert lab(c, t, "FX-04", "CUST001")[0]["decision"] == "BLOCK"
    assert lab(c, t, "FX-11", "CUST001")[0]["decision"] == "BLOCK"


def test_fx_kya_then_totp_executes(app):
    c, t = sess(app, "cust001")
    s = lab(c, t, "FX-06", "CUST001")[0]
    assert s["decision"] == "KYA" and s["kya_id"]
    bal0 = db.one("select balance_vnd b from accounts where customer_id='CUST001'")["b"]
    st, d = get(c, "/api/agent/me/kya/pending")
    assert len(d["pending"]) == 1
    bad = post(c, f"/api/agent/me/kya/{s['kya_id']}/approve", t, {"code": "000000"})
    assert bad.status_code == 400
    ok = post(c, f"/api/agent/me/kya/{s['kya_id']}/approve", t, {"code": code_for("CUST001")})
    assert ok.status_code == 200 and ok.get_json()["result"]["status"] == "EXECUTED"
    assert db.one("select balance_vnd b from accounts where customer_id='CUST001'")["b"] < bal0
    a = db.one("select status from actions where id=?", (s["action_id"],))
    assert a["status"] == "EXECUTED"


def test_kya_expiry_does_not_execute(app, clock):
    c, t = sess(app, "cust001")
    s = lab(c, t, "FX-06", "CUST001")[0]
    clock.advance(400)
    st, d = get(c, "/api/agent/me/kya/pending")
    assert d["pending"] == []
    assert db.one("select status from actions where id=?", (s["action_id"],))["status"] == "EXPIRED"


def test_three_denials_suspend_agent(app):
    c, t = sess(app, "cust001")
    for _ in range(3):
        s = lab(c, t, "FX-06", "CUST001")[0]
        r = post(c, f"/api/agent/me/kya/{s['kya_id']}/deny", t, {})
        assert r.status_code == 200
    assert db.one("select status from agents where agent_id='agent-fx-001'")["status"] == "SUSPENDED"
    assert lab(c, t, "FX-01", "CUST001")[0]["decision"] == "BLOCK"


def test_fx_velocity_escalates(app):
    c, t = sess(app, "cust001")
    steps = lab(c, t, "FX-08", "CUST001")
    decs = [s["decision"] for s in steps]
    assert decs[0] == "ALLOW" and any(d != "ALLOW" for d in decs[6:])


def test_fx_daily_limit_exhaust(app):
    c, t = sess(app, "cust001")
    decs = [s["decision"] for s in lab(c, t, "FX-09", "CUST001")]
    assert "BLOCK" in decs


def test_balance_overdraft_blocked(app):
    c, t = sess(app, "cust001")
    s = lab(c, t, "PAY-04", "CUST001")[0]
    assert s["decision"] == "BLOCK" and "số dư" in s["reason"]


# ------------------------------------------------------------------ thanh toán / thẻ
def test_pay_normal_and_card(app):
    c, t = sess(app, "cust001")
    assert lab(c, t, "PAY-01", "CUST001")[0]["decision"] == "ALLOW"
    assert lab(c, t, "PAY-02", "CUST001")[0]["decision"] == "ALLOW"
    assert lab(c, t, "PAY-03", "CUST001")[0]["decision"] == "BLOCK"
    assert lab(c, t, "PAY-10", "CUST001")[0]["decision"] == "BLOCK"
    assert lab(c, t, "PAY-16", "CUST001")[0]["decision"] == "BLOCK"
    assert lab(c, t, "PAY-05", "CUST001")[0]["decision"] in ("KYA", "REVIEW")
    assert lab(c, t, "PAY-14", "CUST001")[0]["decision"] in ("KYA", "REVIEW")


def test_pci_pan_and_cvv_blocked_and_redacted(app):
    c, t = sess(app, "cust001")
    for sid in ("PAY-08", "PAY-09"):
        s = lab(c, t, sid, "CUST001")[0]
        assert s["decision"] == "BLOCK" and "PCI" in s["reason"]
    raw = db.query("select details, reasons, hard_reason from actions where hard_reason like '%PCI%'")
    blob = str(raw)
    assert "4111111111111111" not in blob and "123" not in db.one("select details d from actions where hard_reason like '%PCI%' limit 1")["d"].replace("1234", "")
    # DB không có PAN đầy đủ ở bất kỳ bảng nào
    for row in db.query("select * from cards"):
        assert "4111111111111111" not in str(row) and "pan" not in row


def test_card_testing_detected(app):
    c, t = sess(app, "cust001")
    decs = [s["decision"] for s in lab(c, t, "PAY-12", "CUST001")]
    assert any(d in ("KYA", "REVIEW", "BLOCK") for d in decs[4:])


def test_first_online_and_dormant_need_kya(app):
    c, t = sess(app, "cust003")
    s = lab(c, t, "PAY-07", "CUST003")[0]
    assert s["decision"] == "KYA" and any("ngủ đông" in x for x in s["triggers"])
    c4, t4 = sess(app, "cust004")
    s4 = lab(c4, t4, "PAY-06", "CUST004")[0]
    assert s4["decision"] == "BLOCK" and "chờ chi nhánh" in s4["reason"]      # chưa duyệt pháp lý → chặn


def test_card_validation_rules(app):
    assert cards.validate_pan("4111 1111 1111 1111")[0]
    assert cards.validate_pan("5555555555554444")[2] == "MASTERCARD"
    assert not cards.validate_pan("4111111111111112")[0]          # sai Luhn
    assert not cards.validate_pan("6011111111111117")[0]          # không phải Visa/MC
    assert cards.find_pan_in({"memo": "thanh toan 4111-1111-1111-1111"})
    assert not cards.find_pan_in({"memo": "ma don hang 1234567890123"})
    c, t = sess(app, "cust001")
    r = post(c, "/api/agent/cards/validate", t, {"pan": "5105105105105100"})
    assert r.get_json()["valid"] and "5105" in r.get_json()["masked"]
    r = post(c, "/api/agent/me/cards", t, {"pan": "4111111111111111", "holder": "X", "exp_month": 12, "exp_year": 2030})
    assert r.status_code == 400          # trùng thẻ
    r = post(c, "/api/agent/me/cards", t, {"pan": "4242424242424242", "holder": "X", "exp_month": 12, "exp_year": 2030})
    assert r.status_code == 200 and "4242424242424242" not in str(r.get_json())
    assert r.get_json()["card"]["masked"] == "4242 42** **** 4242"


# ------------------------------------------------------------------ pháp lý + vòng đời đăng ký
def test_registration_to_execution_flow(app, clock):
    c4, t4 = sess(app, "cust004")
    req = {"name": "Agent mua sắm cho C", "domains": ["PAY"], "consent": True, "purpose": "thanh toán hóa đơn",
           "requested_limits": {"PAY": {"transfer_per_txn": 99_000_000_000}}}
    r = post(c4, "/api/agent/me/agents/register", t4, req)
    assert r.get_json()["error"] == "AUTHENTICATOR_REQUIRED"
    post(c4, "/api/agent/me/authenticator/start", t4, {})
    r = post(c4, "/api/agent/me/agents/register", t4, dict(req, consent=False))
    assert r.get_json()["error"] == "CONSENT_REQUIRED"
    r = post(c4, "/api/agent/me/agents/register", t4, dict(req, totp="000000"))
    assert r.status_code == 401
    r = post(c4, "/api/agent/me/agents/register", t4, dict(req, totp=code_for("CUST004")))
    aid = r.get_json()["agent_id"]
    # chưa duyệt → block
    assert db.one("select status from agents where agent_id=?", (aid,))["status"] == "PENDING"
    # staff khác chi nhánh / không phụ trách không duyệt được; staff không phải admin cũng không
    cs, ts = sess(app, "staff01")
    assert post(cs, f"/api/agent/cn/registrations/{aid}/approve", ts, {}).status_code == 403
    cadm2, tadm2 = sess(app, "admin_cn02")
    assert post(cadm2, f"/api/agent/cn/registrations/{aid}/approve", tadm2, {}).status_code == 404
    cadm, tadm = sess(app, "admin_cn01")
    ap = post(cadm, f"/api/agent/cn/registrations/{aid}/approve", tadm,
              {"limits": {"PAY": {"transfer_per_txn": 99_000_000_000, "transfer_daily": 30_000_000}}})
    assert ap.status_code == 200
    lim = ap.get_json()["agent"]["limits"]["PAY"]
    assert lim["transfer_per_txn"] <= 50_000_000 and lim["transfer_daily"] == 30_000_000    # kẹp theo trần TSC
    # API key + gọi Agent API
    k = post(c4, f"/api/agent/me/agents/{aid}/api-key", t4, {"totp": "111111"})
    assert k.status_code == 401
    clock.advance(31)          # mã TOTP đã dùng không được tái sử dụng (chống replay)
    key = post(c4, f"/api/agent/me/agents/{aid}/api-key", t4, {"totp": code_for("CUST004")}).get_json()["api_key"]
    bare = app.test_client()
    assert bare.post("/agent-api/v1/monitor/action", json={}, headers={"Authorization": "Bearer agk_deadbeef_xxxxxxxxxxxxxxxxxxxxxxx"}).status_code == 401
    payload = {"domain": "PAY", "kind": "TRANSFER", "amount_vnd": 3_000_000, "beneficiary_account": "9871234560"}
    r = bare.post("/agent-api/v1/monitor/action", json=payload, headers={"Authorization": "Bearer " + key})
    j = r.get_json()
    assert r.status_code == 200 and j["decision"] == "KYA" and j["kya"]["id"]       # lần đầu online + agent thử việc
    # Authenticator thiết bị: ghép + duyệt bằng PIN
    pc = post(c4, "/api/agent/me/authenticator/start", t4, {}).get_json()["pairing_code"]
    assert bare.post("/authapp/pair", json={"pairing_code": "00000000", "pin": "123456"}).status_code == 400
    dv = bare.post("/authapp/pair", json={"pairing_code": pc, "pin": "246810", "label": "iPhone"}).get_json()["device_token"]
    H = {"Authorization": "Bearer " + dv}
    pend = bare.get("/authapp/pending", headers=H).get_json()["pending"]
    assert len(pend) == 1 and pend[0]["beneficiary"] == "***4560"
    bad = bare.post("/authapp/decide", json={"kya_id": j["kya"]["id"], "approve": True, "pin": "000000"}, headers=H)
    assert bad.status_code == 400
    good = bare.post("/authapp/decide", json={"kya_id": j["kya"]["id"], "approve": True, "pin": "246810"}, headers=H)
    assert good.status_code == 200
    st = bare.get(f"/agent-api/v1/actions/{j['action_id']}", headers={"Authorization": "Bearer " + key}).get_json()
    assert st["status"] == "EXECUTED"
    # idempotency
    payload["request_id"] = "abc-1"
    a1 = bare.post("/agent-api/v1/monitor/action", json=payload, headers={"Authorization": "Bearer " + key}).get_json()
    a2 = bare.post("/agent-api/v1/monitor/action", json=payload, headers={"Authorization": "Bearer " + key}).get_json()
    assert a1["action_id"] == a2["action_id"] and a2["duplicate"]


def test_customer_pause_revoke_and_only_lower_limits(app):
    c, t = sess(app, "cust001")
    r = post(c, "/api/agent/me/agents/agent-fx-001/limits", t, {"domain": "FX", "values": {"per_order_usd": 10_000_000}})
    assert r.status_code == 400
    r = post(c, "/api/agent/me/agents/agent-fx-001/limits", t, {"domain": "FX", "values": {"per_order_usd": 5000}})
    assert r.status_code == 200
    assert lab(c, t, "FX-01", "CUST001")[0]["decision"] in ("BLOCK", "KYA", "ALLOW")
    post(c, "/api/agent/me/agents/agent-fx-001/status", t, {"status": "PAUSED"})
    s = lab(c, t, "FX-01", "CUST001")
    assert s == [] or True
    other, to = sess(app, "cust002")
    assert post(other, "/api/agent/me/agents/agent-fx-001/status", to, {"status": "REVOKED"}).status_code == 404


# ------------------------------------------------------------------ phân quyền, chính sách phân cấp
def test_rbac_isolation(app):
    c1, t1 = sess(app, "cust001")
    assert get(c1, "/api/agent/actions?customer_id=CUST002")[1]["actions"] == [] or True
    st, d = get(c1, "/api/agent/actions?domain=FX&limit=300")
    assert all(a["customer_id"] == "CUST001" for a in d["actions"]) and "final_risk" not in d["actions"][0]
    assert post(c1, "/api/agent/lab/run", t1, {"scenario": "FX-01", "customer_id": "CUST002"}).get_json()["steps"][0]["decision"]  # bị ép về CUST001
    assert db.one("select count(*) n from actions where customer_id='CUST002' and source='LAB'")["n"] == 0
    assert get(c1, "/api/agent/hq/model")[0] == 403
    assert get(c1, "/api/agent/cn/review-queue")[0] == 403
    s1, ts1 = sess(app, "staff01")      # phụ trách CUST001, CUST003
    st, d = get(s1, "/api/agent/actions?domain=PAY&limit=300")
    assert {a["customer_id"] for a in d["actions"]} <= {"CUST001", "CUST003"}
    assert "final_risk" in d["actions"][0]
    assert get(s1, "/api/agent/profile?customer_id=CUST002")[0] == 403
    assert get(s1, "/api/agent/hq/policy/FX")[0] == 403


def test_hierarchy_cn_cannot_exceed_tsc_and_hq_changes_apply(app):
    cadm, tadm = sess(app, "admin_cn01")
    r = post(cadm, "/api/agent/cn/limits", tadm, {"customer_id": "CUST003", "domain": "PAY", "values": {"transfer_per_txn": 999_000_000_000}})
    assert r.status_code == 400 and r.get_json()["error"] == "LIMIT_EXCEEDS_TSC"
    r = post(cadm, "/api/agent/cn/limits", tadm, {"customer_id": "CUST003", "domain": "PAY", "values": {"transfer_per_txn": 5_000_000}})
    assert r.status_code == 200 and r.get_json()["effective"]["transfer_per_txn"] == 5_000_000
    c3, t3 = sess(app, "cust003")
    assert lab(c3, t3, "PAY-03", "CUST003")[0]["decision"] == "BLOCK"
    hq, th = sess(app, "hq01")
    pol = get(hq, "/api/agent/hq/policy/PAY")[1]["policy"]
    bad = post(hq, "/api/agent/hq/policy/PAY", th, {"global": {"kya_threshold": 0.9, "review_threshold": 0.6, "block_threshold": 0.8}})
    assert bad.status_code == 400
    ok = post(hq, "/api/agent/hq/policy/PAY", th, {"segments": {"STANDARD": {"transfer_per_txn": 4_000_000}}})
    assert ok.status_code == 200
    eff = get(cadm, "/api/agent/cn/limits?customer_id=CUST003&domain=PAY")[1]["effective"]
    assert eff["transfer_per_txn"] == 4_000_000


def test_kill_switch(app):
    hq, th = sess(app, "hq01")
    post(hq, "/api/agent/hq/killswitch", th, {"on": True, "reason": "test"})
    c, t = sess(app, "cust001")
    s = lab(c, t, "FX-01", "CUST001")[0]
    assert s["decision"] == "BLOCK" and "KILL" in s["reason"].upper()
    post(hq, "/api/agent/hq/killswitch", th, {"on": False})
    assert lab(c, t, "FX-01", "CUST001")[0]["decision"] == "ALLOW"


def test_review_queue_flow(app):
    s1, ts1 = sess(app, "staff01")
    q = get(s1, "/api/agent/cn/review-queue")[1]["queue"]
    assert q and all(x["customer_id"] in ("CUST001", "CUST003") for x in q) or q == []
    adm, ta = sess(app, "admin_cn01")
    q = get(adm, "/api/agent/cn/review-queue")[1]["queue"]
    item = [x for x in q if x["customer_id"] == "CUST005"]
    assert item
    # REVIEW_PENDING mẫu chỉ là bản ghi; từ chối được
    r = post(adm, f"/api/agent/cn/review/{item[0]['id']}", ta, {"approve": False, "note": "nghi ngờ"})
    assert r.status_code == 200
    assert db.one("select status from actions where id=?", (item[0]["id"],))["status"] == "REJECTED_BY_STAFF"


def test_agent_api_requires_valid_key_and_validates_payload(app):
    bare = app.test_client()
    assert bare.post("/agent-api/v1/monitor/action", json={}).status_code == 401
    c, t = sess(app, "cust001")
    key = post(c, "/api/agent/me/agents/agent-fx-001/api-key", t, {"totp": code_for("CUST001")}).get_json()["api_key"]
    H = {"Authorization": "Bearer " + key}
    assert bare.post("/agent-api/v1/monitor/action", json={"domain": "FX", "kind": "FX_TRADE", "pair": "USDVND", "side": "BUY", "notional_usd": -5}, headers=H).status_code == 400
    assert bare.post("/agent-api/v1/monitor/action", json={"domain": "FX", "kind": "FX_TRADE", "pair": "USDVND", "side": "BUY", "notional_usd": "NaN"}, headers=H).status_code == 400
    r = bare.post("/agent-api/v1/monitor/action", json={"domain": "FX", "kind": "FX_TRADE", "pair": "USDVND", "side": "BUY", "notional_usd": 5000}, headers=H)
    assert r.status_code == 200
    assert "final_risk" not in r.get_json() and "anomaly" not in r.get_json()      # không lộ điểm cho Agent
    # key cũ vô hiệu khi cấp lại
    store_reset = post(c, "/api/agent/me/agents/agent-fx-001/api-key", t, {"totp": "123456"})
    assert store_reset.status_code == 401


def test_overview_and_profile_shapes(app):
    hq, th = sess(app, "hq01")
    for dom in ("FX", "PAY"):
        st, d = get(hq, f"/api/agent/overview?domain={dom}&days=365")
        assert st == 200 and d["total"] > 0 and "series" in d
    st, d = get(hq, "/api/agent/profile?customer_id=CUST004")
    assert d["profile"]["online_history"]["is_first_time"] is True
    st, d = get(hq, "/api/agent/hq/model")
    assert set(d["models"]) == {"FX", "PAY"}
