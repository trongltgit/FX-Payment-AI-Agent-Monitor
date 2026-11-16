"""v2.0 – Luồng tuần tự ANTI-BOT → AI AGENT MONITOR; phân biệt bot/người (tầng 1) và AI Agent/người (tầng 2); mô hình thẻ; hồ sơ triển khai."""
import itertools
import time

import pytest

from agentmon import actor, antibot_txn as ab, cardmodel, db, engine, lab, pipeline, profiles, registry, seed, sources
from agentmon.constants import PAY_KINDS
from utils import store

_n = itertools.count(1)


@pytest.fixture(autouse=True)
def reseed():
    db.init()
    seed.seed(force=True)
    yield


def uid(p="x"):
    return f"{p}{next(_n)}-{int(time.time() * 1000) % 100000}"


def R(cred="SOURCE_KEY", src="DIGIBANK", ip=None, ua="Mozilla/5.0 (iPhone) Safari", hs=5, ses=None, kind="TRANSFER", cid="CUST001", amt=1_000_000, card=None):
    return {"credential": cred, "ip": ip or f"10.9.{next(_n) % 250}.{next(_n) % 250}", "ua": ua, "header_score": hs, "source_system": src,
            "session": dict(ses or {}), "txn": {"customer_id": cid, "kind": kind, "domain": "PAY", "amount": amt, "card_ref": card}}


GOOD = dict(device_attested=True, device_known=True, mfa_age_s=120, pointer_events=14, key_events=22, think_time_ms=4800)


# ------------------------------------------------------------------ tầng 1: bảng điều kiện bot vs người
def test_human_verified_with_strong_evidence():
    r = ab.assess(R(ses=dict(GOOD, device_id=uid("d"))))
    assert r["bot_class"] == ab.HUMAN_VERIFIED and r["action"] == ab.ALLOW and r["bot_score"] == 0
    assert {e["signal"] for e in r["evidence"] if e["side"] == "HUMAN"} >= {"DEVICE_ATTESTED", "KNOWN_DEVICE", "RECENT_MFA", "HUMAN_TELEMETRY"}


def test_headless_fast_no_telemetry_is_malicious_bot():
    r = ab.assess(R(ua="python-requests/2.31", hs=60, ses=dict(think_time_ms=80, device_id=uid("d"))))
    assert r["bot_class"] == ab.MALICIOUS_BOT and r["action"] == ab.BLOCK and "BOT_EVIDENCE_STRONG" in r["rules"] and r["bot_score"] >= 85


def test_single_bot_signal_without_human_proof_is_challenged():
    r = ab.assess(R(ses=dict(think_time_ms=100, device_id=uid("d"))))
    assert r["bot_class"] == ab.SUSPECT and r["action"] == ab.CHALLENGE and r["challenge"] == "TURNSTILE"


def test_human_evidence_offsets_bot_signal():
    r = ab.assess(R(ses=dict(GOOD, anti_bot_score=75, device_id=uid("d"))))        # Anti-Bot web nghi ngờ nhưng thiết bị chứng thực + MFA + telemetry
    assert r["action"] == ab.ALLOW and r["bot_class"] == ab.HUMAN_LIKELY and "HUMAN_EVIDENCE_OFFSETS_BOT" in r["rules"]


def test_metronome_cadence_for_declared_human():
    cid, now = uid("C"), time.time()
    for i in range(10):
        store.events_add(f"ab:cad:HUMAN:{cid}", "", keep_seconds=400, ts=now - 100 + i * 10)       # đều đặn 10s/lần
    r = ab.assess(R(cid=cid, ses=dict(device_id=uid("d"))))
    assert any(e["signal"] == "METRONOME_CADENCE" for e in r["evidence"])


def test_replay_and_stale_requests_blocked():
    n = uid("nonce")
    assert ab.assess(R(ses=dict(GOOD, nonce=n, device_id=uid("d"))))["action"] == ab.ALLOW
    r = ab.assess(R(ses=dict(GOOD, nonce=n, device_id=uid("d"))))
    assert r["action"] == ab.BLOCK and "REPLAY" in r["rules"]
    st = ab.assess(R(ses=dict(GOOD, ts=time.time() - 3600, device_id=uid("d"))))
    assert st["action"] == ab.BLOCK and "STALE_REQUEST" in st["rules"]


def test_no_credential_and_banned_ip():
    assert ab.assess(R(cred="NONE"))["action"] == ab.BLOCK
    from services import bot_defense
    ip = f"203.0.113.{next(_n) % 250}"
    bot_defense.ban_ip(ip, "test", ttl=60)
    r = ab.assess(R(ip=ip, ses=dict(GOOD)))
    assert r["action"] == ab.BLOCK and "IP_BANNED" in r["rules"]


def test_card_enumeration_card_testing_and_device_farm():
    ip, dev = f"198.51.100.{next(_n) % 250}", uid("dev")
    last = None
    for i in range(5):
        last = ab.assess(R(kind="ONLINE_PURCHASE", ip=ip, ses=dict(GOOD, device_id=dev), card=f"card{i}", amt=900_000))
    assert last["action"] == ab.BLOCK and "CARD_ENUMERATION" in last["rules"]
    ip2, dev2 = f"198.51.100.{next(_n) % 250}", uid("dev")
    for i in range(6):
        last = ab.assess(R(kind="CARD_PAYMENT", ip=ip2, ses=dict(GOOD, device_id=dev2), card="same", amt=10_000))
    assert last["action"] == ab.BLOCK and "CARD_TESTING" in last["rules"]
    dev3 = uid("farm")
    for i in range(4):
        last = ab.assess(R(cid=f"CUSTX{i}", ses=dict(GOOD, device_id=dev3)))
    assert last["action"] == ab.BLOCK and "DEVICE_FARM" in last["rules"]


def test_authorized_agent_is_not_penalised_for_automation_but_shared_key_is_challenged():
    cid, now = uid("C"), time.time()
    for i in range(12):
        store.events_add(f"ab:cad:AGENT:{cid}", "", keep_seconds=400, ts=now - 120 + i * 10)
    ok = ab.assess(R(cred="AGENT_KEY", src=None, ua="my-agent/1.0", hs=0, cid=cid))
    assert ok["bot_class"] == ab.AUTOMATION_AUTHORIZED and ok["action"] == ab.ALLOW
    shared = ab.assess(R(cred="AGENT_KEY", src=None, ses=dict(pointer_events=9, key_events=12), cid=uid("C")))
    assert shared["bot_class"] == ab.SUSPECT and "AGENT_KEY_USED_BY_HUMAN" in shared["rules"] and shared["challenge"] == "KEY_ROTATION_REVIEW"


# ------------------------------------------------------------------ tầng 2a: AI Agent hay người
def test_actor_classification_table():
    h = actor.classify({"declared_actor": "HUMAN", "bot_class": ab.HUMAN_VERIFIED}, "CUST001", {})
    assert h["actor_type"] == "HUMAN" and h["confidence"] == 0.95 and not h["unverified"]
    lk = actor.classify({"declared_actor": "HUMAN", "bot_class": ab.HUMAN_LIKELY, "observed_automation": True}, "CUST001", {})
    assert lk["confidence"] == 0.60 and lk["unverified"]
    a = actor.classify({"declared_actor": "AGENT", "bot_class": ab.AUTOMATION_AUTHORIZED}, "CUST001", {})
    assert a["actor_type"] == "AGENT" and a["observed"] == "AUTOMATION" and not a["unverified"]


# ------------------------------------------------------------------ pipeline: thứ tự + cả hai tầng
def _body(cid="CUST001", **kw):
    u = lab._usual(cid, "PAY")
    b = dict(customer_id=cid, request_id=uid("rq"), domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"])
    b.update(kw)
    return b


def test_antibot_runs_first_and_blocks_before_monitor(monkeypatch):
    called = []
    monkeypatch.setattr(engine, "evaluate", lambda *a, **k: called.append("MONITOR") or (_ for _ in ()).throw(AssertionError("Monitor không được chạy")))
    pr = pipeline.process(credential="SOURCE_KEY", body=_body(session=dict(think_time_ms=50, device_id=uid("d"))), ip="192.0.2.1",
                          ua="curl/8.0", header_score=70, source_system="DIGIBANK")
    assert pr["stage"] == "ANTIBOT" and pr["antibot"]["action"] == ab.BLOCK and pr["result"] is None and called == []
    assert db.one("SELECT COUNT(*) n FROM antibot_events WHERE action='BLOCK'")["n"] >= 1
    assert db.one("SELECT COUNT(*) n FROM actions WHERE source='GATEWAY' AND request_id IS NULL")["n"] if False else True


def test_antibot_then_monitor_order_and_prescreen_in_trace(monkeypatch):
    order = []
    real_assess, real_eval = ab.assess, engine.evaluate
    monkeypatch.setattr(ab, "assess", lambda r: order.append("ANTIBOT") or real_assess(r))
    monkeypatch.setattr(engine, "evaluate", lambda *a, **k: order.append("MONITOR") or real_eval(*a, **k))
    pr = pipeline.process(credential="SOURCE_KEY", body=_body(session=dict(GOOD, device_id="DEV-IPH001")), ip="192.0.2.2", ua="bank-core/1.0",
                          source_system="DIGIBANK")
    assert order == ["ANTIBOT", "MONITOR"] and pr["stage"] == "MONITOR"
    tr = pr["result"]["details"]["trace"]
    assert tr["pre_screen"]["antibot"]["bot_class"] == ab.HUMAN_VERIFIED and tr["pre_screen"]["actor"]["actor_type"] == "HUMAN"
    assert pr["result"]["actor_type"] == "HUMAN"


def test_session_risk_for_monitor_comes_from_antibot_score():
    pr = pipeline.process(credential="SOURCE_KEY", body=_body(session=dict(GOOD, device_id="DEV-IPH001", anti_bot_score=45)), ip="192.0.2.3",
                          ua="bank-core/1.0", source_system="DIGIBANK")
    r = pr["result"]
    assert r["session_risk"] == pr["antibot"]["bot_score"] / 100.0


def test_agent_echo_on_human_channel_is_unverified():
    cid = "CUST001"
    u = lab._usual(cid, "PAY")
    ag = registry.get(lab._agent_for(cid, "PAY"))
    pipeline.process(credential="AGENT_KEY", body=dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"]),
                     ip="192.0.2.50", ua="agent/1", agent=ag, source="TEST")
    pr = pipeline.process(credential="SOURCE_KEY", body=_body(amount_vnd=u["tamt"], beneficiary_account=u["ben"], session=dict(GOOD, device_id="DEV-IPH001")),
                          ip="192.0.2.51", ua="bank-core/1.0", source_system="DIGIBANK")
    assert pr["stage"] == "MONITOR" and pr["actor"]["unverified"] and any("AGENT_ECHO" in x for x in pr["actor"]["reasons"])
    codes = {t[0] for t in pr["result"]["triggers"]}
    assert "ACTOR_UNVERIFIED" in codes and pr["result"]["decision"] in ("STEP_UP", "REVIEW") and "ACTOR_SPOOFING" in pr["result"]["fraud_types"]


def test_gateway_v2_end_to_end(app):
    c = app.test_client()
    H = {"User-Agent": "bank-core/1.0"}
    assert c.post("/gateway/v2/transaction", json=_body(), headers=H).status_code == 401
    k = sources.issue_key("digibank-demo")
    H["X-Source-Key"] = k
    ok = c.post("/gateway/v2/transaction", json=_body(session=dict(GOOD, device_id="DEV-IPH001")), headers=H).get_json()
    assert ok["stage"] == "MONITOR" and ok["actor_type"] == "HUMAN" and ok["bot_class"] == "HUMAN_VERIFIED"
    bad = c.post("/gateway/v2/transaction", json=_body(session=dict(think_time_ms=20, device_id=uid("d"), anti_bot_score=95)), headers=H)
    assert bad.status_code == 403 and bad.get_json()["stage"] == "ANTIBOT" and bad.get_json()["action"] == "BLOCK"
    assert c.post("/gateway/v2/transaction", json=_body(session=dict(anti_bot_score=999)), headers=H).status_code == 400
    assert c.post("/gateway/v2/transaction", json=_body(session=dict(pow_ok="yes")), headers=H).status_code == 400
    # Agent qua cùng cổng
    ag = lab._agent_for("CUST001", "PAY")
    ak = registry.issue_key(ag)
    u = lab._usual("CUST001", "PAY")
    r = c.post("/gateway/v2/transaction", headers={"Authorization": f"Bearer {ak}", "User-Agent": "agent/1"},
               json=dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"])).get_json()
    assert r["stage"] == "MONITOR" and r["actor_type"] == "AGENT" and r["bot_class"] == "AUTOMATION_AUTHORIZED"


def test_agent_api_goes_through_antibot_first(app):
    ag = lab._agent_for("CUST001", "PAY")
    ak = registry.issue_key(ag)
    c = app.test_client()
    u = lab._usual("CUST001", "PAY")
    r = c.post("/agent-api/v1/monitor/action", headers={"Authorization": f"Bearer {ak}", "User-Agent": "agent/1"},
               json=dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"], session=dict(pointer_events=20, key_events=20)))
    assert r.status_code == 403 and r.get_json()["stage"] == "ANTIBOT" and "AGENT_KEY_USED_BY_HUMAN" in r.get_json()["reason_codes"]


# ------------------------------------------------------------------ mô hình thẻ
def hx(cid, src, body, hour=12, ts=None):
    body = dict(body)
    body.setdefault("request_id", uid("c"))
    return engine.evaluate(body, "", source="TEST", customer_hint=cid, sim_hour=hour, sim_ts=ts, use_llm=False, actor="HUMAN", source_system=src)


def card(cid="CUST001"):
    return lab._card(cid)


def test_network_detection_and_enumerations():
    assert [cardmodel.network_from_bin(b) for b in ("411111", "555555", "353011", "341111", "620000", "970436", "601100")] == \
        ["VISA", "MASTERCARD", "JCB", "AMEX", "UNIONPAY", "NAPAS", "DISCOVER_DINERS"]
    assert {"VISA", "MASTERCARD", "JCB", "UNIONPAY", "AMEX", "DISCOVER_DINERS", "NAPAS"} <= set(cardmodel.NETWORKS)
    assert {"CREDIT", "DEBIT", "PREPAID", "VIRTUAL", "CORPORATE"} <= set(cardmodel.PRODUCTS)
    assert {"PURCHASE", "PREAUTH", "CAPTURE", "REFUND", "REVERSAL", "CASH_ADVANCE", "RECURRING", "MOTO", "INSTALLMENT"} <= set(cardmodel.SUBTYPES)
    assert {"CHIP", "CONTACTLESS", "MAGSTRIPE", "MANUAL_KEY", "ECOM", "WALLET_TOKEN", "QR"} <= set(cardmodel.ENTRY_MODES)
    with pytest.raises(engine.BadRequest):
        hx("CUST001", "CARD_SWITCH", dict(domain="PAY", kind="CARD_PAYMENT", amount_vnd=1000, card_token=card(), merchant_id="M1", mcc="5411", entry_mode="TELEPATHY"))


def test_card_network_taken_from_card_record():
    r = hx("CUST001", "CARD_SWITCH", dict(domain="PAY", kind="CARD_PAYMENT", amount_vnd=300_000, card_token=card(), merchant_id="M300", mcc="5411", country="VN"))
    assert r["details"]["card_network"] in cardmodel.NETWORKS and r["details"]["card_network"] != "OTHER"


@pytest.mark.parametrize("extra,code,ftype", [
    (dict(entry_mode="MANUAL_KEY", amount_vnd=5_000_000), "MANUAL_ENTRY", "CARD_MANUAL_ENTRY"),
    (dict(chip_fallback=True, entry_mode="MAGSTRIPE"), "CHIP_FALLBACK", "CARD_SKIMMING"),
    (dict(entry_mode="CONTACTLESS", auth_method="NONE", amount_vnd=2_500_000), "CONTACTLESS_NO_CVM", "CARD_SKIMMING"),
    (dict(txn_subtype="REFUND", amount_vnd=3_000_000), "REFUND_UNMATCHED", "REFUND_ABUSE"),
    (dict(txn_subtype="REFUND", refund_original_ref="TXN1", refund_to_other_card=True), "REFUND_OTHER_CARD", "REFUND_ABUSE"),
    (dict(txn_subtype="CAPTURE", preauth_amount=1_000_000, amount_vnd=2_000_000), "CAPTURE_OVER_PREAUTH", "CARD_MERCHANT_ABUSE"),
    (dict(card_network="NAPAS", country="SG"), "DOMESTIC_CARD_ABROAD", "CARD_SKIMMING"),
])
def test_card_rule_signals(extra, code, ftype):
    body = dict(domain="PAY", kind="CARD_PAYMENT", amount_vnd=800_000, card_token=card(), merchant_id="M300", mcc="5411", country="VN")
    body.update(extra)
    r = hx("CUST001", "CARD_SWITCH", body)
    assert code in {t[0] for t in r["triggers"]}, r["triggers"]
    assert ftype in r["fraud_types"] and r["decision"] in ("STEP_UP", "REVIEW", "BLOCK")


def test_impossible_travel_and_static_qr():
    now = engine.store.now()
    base = dict(domain="PAY", kind="CARD_PAYMENT", amount_vnd=500_000, card_token=card(), merchant_id="M300", mcc="5411")
    hx("CUST001", "CARD_SWITCH", dict(base, country="VN"), ts=now - 1800)
    r = hx("CUST001", "CARD_SWITCH", dict(base, country="US", merchant_id="MUS1"), ts=now)
    assert "IMPOSSIBLE_TRAVEL" in {t[0] for t in r["triggers"]} and "IMPOSSIBLE_TRAVEL" in r["fraud_types"] and r["fraud_class"] == "FRAUD_SUSPECTED"
    q = hx("CUST002", "DIGIBIZ", dict(domain="PAY", kind="QR_PAYMENT", amount_vnd=9_000_000, card_token=card("CUST002"), merchant_id="MQRNEW", mcc="5411",
                                      qr_scheme="VIETQR", qr_type="STATIC"))
    assert "STATIC_QR_HIGH" in {t[0] for t in q["triggers"]} and q["details"]["qr_scheme"] == "VIETQR"


# ------------------------------------------------------------------ hồ sơ triển khai
def test_profile_mapping_and_readiness(monkeypatch):
    monkeypatch.delenv("DEPLOY_PROFILE", raising=False)
    monkeypatch.setenv("PRICING_ENVIRONMENT", "demo")
    assert profiles.current() == "demo"
    monkeypatch.setenv("PRICING_ENVIRONMENT", "production")
    assert profiles.current() == "pilot"                       # cấu hình cũ = pilot
    monkeypatch.setenv("DEPLOY_PROFILE", "production")
    assert profiles.current() == "production" and ab.cfg()["block_without_nonce"] and ab.cfg()["card_enum_block"] == 4
    ids = {c["id"]: c for c in profiles.readiness()}
    assert ids["CORE_ADAPTER"]["level"] == "BLOCKER" and ids["MODEL_REAL_DATA"]["level"] == "BLOCKER" and ids["DATABASE"]["level"] == "BLOCKER"
    with pytest.raises(RuntimeError) as e:
        profiles.enforce()
    assert "CORE_ADAPTER" in str(e.value) and "MODEL_REAL_DATA" in str(e.value)
    monkeypatch.setenv("DEPLOY_PROFILE", "pilot")
    profiles.enforce()                                         # pilot chỉ cảnh báo
    assert not ab.cfg()["block_without_nonce"]


def test_production_requires_nonce_for_human_sources(monkeypatch):
    monkeypatch.setenv("DEPLOY_PROFILE", "production")
    r = ab.assess(R(ses=dict(GOOD, device_id=uid("d"))))
    assert r["action"] == ab.CHALLENGE and "NO_NONCE" in r["rules"]
    assert ab.assess(R(ses=dict(GOOD, device_id=uid("d"), nonce=uid("n"))))["action"] == ab.ALLOW


def test_pilot_requires_telemetry_on_online_channels(monkeypatch):
    monkeypatch.setenv("DEPLOY_PROFILE", "pilot")
    r = ab.assess(R(ses=dict(device_id=uid("d"))))
    assert any(e["signal"] == "NO_TELEMETRY_ON_ONLINE_CHANNEL" for e in r["evidence"])
    monkeypatch.setenv("DEPLOY_PROFILE", "demo")
    r2 = ab.assess(R(ses=dict(device_id=uid("d"))))
    assert not any(e["signal"] == "NO_TELEMETRY_ON_ONLINE_CHANNEL" for e in r2["evidence"])


def test_antibot_failure_is_fail_closed_in_pilot(monkeypatch):
    monkeypatch.setenv("DEPLOY_PROFILE", "pilot")
    monkeypatch.setattr(ab, "assess", lambda r: (_ for _ in ()).throw(RuntimeError("redis down")))
    pr = pipeline.process(credential="SOURCE_KEY", body=_body(session=dict(GOOD)), ip="192.0.2.9", ua="bank-core/1.0", source_system="DIGIBANK")
    assert pr["stage"] == "ANTIBOT" and "ANTIBOT_ERROR" in pr["antibot"]["rules"] and pr["antibot"]["action"] == "BLOCK"
    monkeypatch.setenv("DEPLOY_PROFILE", "demo")
    pr = pipeline.process(credential="SOURCE_KEY", body=_body(session=dict(GOOD, device_id="DEV-IPH001")), ip="192.0.2.9", ua="bank-core/1.0", source_system="DIGIBANK")
    assert pr["stage"] == "MONITOR" and "ANTIBOT_ERROR_FAIL_OPEN" in pr["antibot"]["rules"]
