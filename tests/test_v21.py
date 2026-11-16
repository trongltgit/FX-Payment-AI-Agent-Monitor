"""v2.1 – sinh trắc khuôn mặt & danh tính tại ATM, thanh toán sao kê, mô hình AI bổ sung (bot–người, boosting giám sát, chuỗi, đồ thị)."""
import itertools
import time

import pytest

from agentmon import antibot_txn as ab, atm_identity, biometrics, botmodel, db, engine, fraudgbm, graphrisk, lab, ml, pipeline, profiles, seed, seqmodel
from tests.test_v2 import GOOD, R, uid

_n = itertools.count(1)


@pytest.fixture(autouse=True)
def reseed():
    db.init()
    seed.seed(force=True)
    yield


# ------------------------------------------------------------------ sinh trắc
def test_enrollment_requires_consent_and_is_encrypted_at_rest():
    emb = biometrics.demo_embedding("khach-moi")
    with pytest.raises(PermissionError):
        biometrics.enroll("CUSTNEW", emb, consent=False)
    biometrics.enroll("CUSTNEW", emb, consent=True)
    blob = db.one("SELECT blob FROM biometric_templates WHERE customer_id='CUSTNEW'")["blob"]
    assert str(round(emb[0], 4)) not in blob and "[" not in blob            # không lưu embedding dạng rõ
    assert biometrics.enrolled("CUSTNEW") and biometrics.match_score("CUSTNEW", emb) > 0.99
    biometrics.delete("CUSTNEW")
    assert not biometrics.enrolled("CUSTNEW")
    with pytest.raises(ValueError):
        biometrics.enroll("X", [1, 2, 3], consent=True)


def test_match_calibration_same_vs_different_person():
    e = biometrics.demo_embedding("alice")
    assert biometrics.calibrate(biometrics.cosine(e, biometrics.demo_embedding("alice", noise=0.2, noise_seed=3))) > 0.9
    assert biometrics.calibrate(biometrics.cosine(e, biometrics.demo_embedding("bob"))) < 0.1


@pytest.mark.parametrize("sid,expect", [(s[0], s[4]) for s in lab.HUMAN_SCEN])
def test_human_scenarios(sid, expect):
    s = lab.run_human(sid, "CUST001")["steps"][0]
    assert s["decision"] == expect, s


def test_atm_identity_verdicts_and_who():
    out = {sid: lab.run_human(sid, "CUST001")["steps"][0] for sid in ("H-ATM-01", "H-ATM-02", "H-ATM-03", "H-ATM-05", "H-ATM-06")}
    assert out["H-ATM-01"]["who"] == "CUSTOMER" and out["H-ATM-02"]["who"] == "THIRD_PARTY" and out["H-ATM-03"]["who"] == "SPOOF" and out["H-ATM-05"]["who"] == "NO_PERSON"
    assert out["H-ATM-06"]["step_up_method"] == "APP_CONFIRM" and out["H-ATM-02"]["fraud_class"] == "FRAUD_SUSPECTED"


def test_atm_without_camera_channel_keeps_previous_behaviour():
    tok, u = lab._card("CUST001"), lab._usual("CUST001", "PAY")
    r = engine.evaluate(dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=u.get("atm_amt") or 3_000_000, card_token=tok, atm_id=u.get("atm_ref") or "ATM0101", request_id=uid("a")),
                        "", customer_hint="CUST001", sim_hour=u["hour"], use_llm=False, actor="HUMAN", source_system="ATM_SWITCH")
    assert r["details"]["atm_identity"]["verdict"] == "NO_BIOMETRIC_CHANNEL" and r["decision"] == "ALLOW"


def test_ai_agent_cannot_withdraw_cash_without_cardholder_confirmation():
    s = lab.run("PAY-17", "CUST001")["steps"][0]
    assert s["decision"] == "KYA" and "AGENT_CASH_OUT" in s["fraud_types"]


def test_atm_card_collection_signal():
    tok_by = {c: lab._card(c) for c in ("CUST001", "CUST002", "CUST003", "CUST005", "CUST004")}
    last = None
    for c, tok in tok_by.items():
        lab.prepare(c)
        last = engine.evaluate(dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=500_000, card_token=tok, atm_id="ATM-HOT-1", request_id=uid("h")),
                               "", customer_hint=c, sim_hour=12, use_llm=False, actor="HUMAN", source_system="ATM_SWITCH")
    assert "ATM_CARD_COLLECTION" in {t[0] for t in last["triggers"]} and "ATM_CARD_COLLECTION" in last["fraud_types"]


def test_biometric_inputs_are_validated():
    tok = lab._card("CUST001")
    base = dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=500_000, card_token=tok, atm_id="ATM1")
    for bad in (dict(liveness_score=1.5), dict(camera_status="LASER"), dict(faces_in_frame=-1), dict(face_embedding=[1, 2, 3])):
        with pytest.raises(engine.BadRequest):
            engine.normalize(dict(base, biometric=dict(face_present=True, **bad)), 1.7e9, None, "HUMAN", "ATM_SWITCH")
    with pytest.raises(engine.BadRequest):
        engine.normalize(dict(base, pin_entry_cv=99), 1.7e9, None, "HUMAN", "ATM_SWITCH")


def test_embedding_is_never_persisted():
    r = lab.run_human("H-ATM-01", "CUST001")["steps"][0]
    row = db.one("SELECT details FROM actions WHERE id=?", (r["action_id"],))["details"]
    assert "face_embedding" not in row and "_face_embedding" not in row


# ------------------------------------------------------------------ Tầng 1: sinh trắc + mô hình bot-người
def test_tier1_presentation_attack_blocked_and_liveness_is_strong_human_evidence():
    bad = ab.assess(R(src="ATM_SWITCH", kind="ATM_WITHDRAWAL", ses=dict(biometric=dict(face_present=True, liveness_score=0.2, injection_attack_score=0.1))))
    assert bad["action"] == ab.BLOCK and "PRESENTATION_ATTACK" in bad["rules"]
    good = ab.assess(R(src="ATM_SWITCH", kind="ATM_WITHDRAWAL", ses=dict(biometric=dict(face_present=True, liveness_score=0.97, injection_attack_score=0.0, face_match_score=0.93))))
    assert good["bot_class"] == ab.HUMAN_VERIFIED and {"BIOMETRIC_LIVENESS", "FACE_MATCHED_ENROLLED"} <= {e["signal"] for e in good["evidence"]}
    none = ab.assess(R(src="ATM_SWITCH", kind="ATM_WITHDRAWAL", ses=dict(biometric=dict(face_present=False, camera_status="OK"))))
    assert none["action"] == ab.BLOCK and "NO_PERSON_AT_ATM" in none["rules"]


def test_pipeline_blocks_deepfake_at_tier1_without_calling_monitor(monkeypatch):
    monkeypatch.setattr(engine, "evaluate", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Monitor không được chạy")))
    body = dict(customer_id="CUST001", request_id=uid("d"), domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=1_000_000, card_token="x", atm_id="ATM1",
                biometric=dict(face_present=True, liveness_score=0.9, injection_attack_score=0.95))
    pr = pipeline.process(credential="SOURCE_KEY", body=body, ip="192.0.2.77", ua="atm-switch/1", source_system="ATM_SWITCH")
    assert pr["stage"] == "ANTIBOT" and "PRESENTATION_ATTACK" in pr["antibot"]["rules"]


def test_bot_model_quality_and_manifest():
    ent = ml.read_manifest()["BOT"]["history"][-1]
    assert ent["holdout"]["auc"] >= 0.95 and ent["holdout"]["flag_at_0.85"]["human_flagged"] <= 0.03 and ent["data_source"].startswith("synthetic")
    naive = botmodel.score(dict(think_time_ms=60, pointer_events=0, key_events=0, header_score=80, anti_bot_score=95))
    human = botmodel.score(dict(think_time_ms=4300, pointer_events=21, key_events=16, pointer_path_entropy=0.8, key_interval_cv=0.5, header_score=8, anti_bot_score=4,
                                session_age_s=320, device_known=True))
    assert naive > 0.9 and human < 0.1
    assert botmodel.score(dict(header_score=10)) is None            # thiếu telemetry → không chấm


def test_ensemble_mode_active_vs_shadow(monkeypatch):
    ses = dict(think_time_ms=60, pointer_events=0, key_events=0, anti_bot_score=90, device_id=uid("d"))
    monkeypatch.setenv("ENSEMBLE_MODE", "active")
    a = ab.assess(R(ua="python-requests/2", hs=70, ses=dict(ses)))
    assert any(e["signal"] == "ML_BOT_HIGH" for e in a["evidence"]) and a["ml_mode"] == "active"
    monkeypatch.setenv("ENSEMBLE_MODE", "shadow")
    s = ab.assess(R(ua="python-requests/2", hs=70, ses=dict(ses, device_id=uid("d"))))
    assert any(e["signal"] == "ML_BOT_PROB" and e["side"] == "SHADOW" for e in s["evidence"]) and not any(e["signal"] == "ML_BOT_HIGH" for e in s["evidence"])
    assert s["ml_bot_prob"] > 0.9


def test_profile_default_ensemble_mode(monkeypatch):
    monkeypatch.delenv("ENSEMBLE_MODE", raising=False)
    for prof, mode in (("demo", "active"), ("pilot", "shadow"), ("production", "shadow")):
        monkeypatch.setenv("DEPLOY_PROFILE", prof)
        assert profiles.ensemble_mode() == mode


# ------------------------------------------------------------------ Monitor: các mô hình bổ sung
def test_supervised_second_opinion_recorded_and_only_raises(monkeypatch):
    monkeypatch.setenv("ENSEMBLE_MODE", "shadow")
    u = lab._usual("CUST001", "PAY")
    r = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"] * 9, beneficiary_account="7777700001", request_id=uid("g")), "", customer_hint="CUST001",
                        sim_hour=3, use_llm=False, actor="HUMAN", source_system="DIGIBANK")
    g = r["details"]["trace"]["scoring"]["components"]["supervised_gbm"]
    assert g["mode"] == "shadow" and 0 <= g["prob"] <= 1 and g["version"].startswith("gbm-pay-") and "SUPERVISED_HIGH_RISK" not in {t[0] for t in r["triggers"]}
    monkeypatch.setenv("ENSEMBLE_MODE", "active")
    r2 = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"] * 9, beneficiary_account="7777700002", request_id=uid("g")), "", customer_hint="CUST001",
                         sim_hour=3, use_llm=False, actor="HUMAN", source_system="DIGIBANK")
    assert r2["details"]["trace"]["scoring"]["components"]["supervised_gbm"]["mode"] == "active"


def test_gbm_manifest_metrics():
    for d in ("FX", "PAY"):
        h = ml.read_manifest()["GBM_" + d]["history"][-1]["holdout"]
        assert h["auc"] > 0.85 and h["at_0.85"]["false_positive_rate"] <= 0.05


def test_sequence_surprise_flags_unusual_transition():
    from agentmon import features as F
    hist = [dict(kind="TRANSFER", channel_type="DIGIBANK", mcc=None, ts=i) for i in range(40, 0, -1)]
    usual = dict(kind="TRANSFER", channel_type="DIGIBANK", mcc=None)
    odd = dict(kind="ATM_WITHDRAWAL", channel_type="ATM", mcc="6011")
    assert seqmodel.surprise(hist, usual) < 0.3 and seqmodel.surprise(hist, odd) > 0.85
    assert seqmodel.surprise(hist[:5], odd) is None


def test_graph_ring_detects_linked_accounts():
    now = time.time()
    for c in ("CUST001", "CUST002", "CUST003", "CUST004", "CUST005", "CUST006"):
        db.execute("INSERT INTO antibot_events(ts,customer_id,source,declared_actor,bot_class,bot_score,action,rules,evidence,ip,device_id,domain,kind) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (now - 60, c, "DIGIBANK", "HUMAN", "HUMAN_LIKELY", 5, "ALLOW", "[]", "[]", "203.0.113.9", "DEV-SHARED-RING", "PAY", "TRANSFER"))
    assert graphrisk.ring_size("CUST001", "DEV-SHARED-RING", None, None, now) == 5
    assert graphrisk.ring_size("CUST001", "DEV-ALONE", None, None, now) == 0
    r = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=1_000_000, beneficiary_account=lab._usual("CUST001", "PAY")["ben"], device_id="DEV-SHARED-RING",
                             request_id=uid("r")), "", customer_hint="CUST001", sim_hour=11, use_llm=False, actor="HUMAN", source_system="DIGIBANK")
    assert r["details"]["trace"]["context"] and r["details"]["trace"]["scoring"]["components"]["ring_size"] >= 5
    assert "LINKED_ACCOUNTS" in {t[0] for t in r["triggers"]} and "FRAUD_RING" in r["fraud_types"]


# ------------------------------------------------------------------ thanh toán sao kê
def test_statement_payment_rules_and_blocked_card_can_still_be_paid():
    tok = lab._card("CUST001")
    db.execute("UPDATE cards SET status='BLOCKED' WHERE token=?", (tok,))
    r = lab.run_human("H-STM-01", "CUST001")["steps"][0]
    assert r["decision"] == "ALLOW"                                        # thẻ khóa vẫn được trả nợ
    with pytest.raises(engine.BadRequest):
        engine.normalize(dict(domain="PAY", kind="CARD_STATEMENT_PAYMENT", amount_vnd=1000, card_token=tok, funding_source_type="BITCOIN"), 1.7e9, None, "HUMAN", "DIGIBANK")
    with pytest.raises(engine.BadRequest):
        engine.normalize(dict(domain="PAY", kind="CARD_STATEMENT_PAYMENT", amount_vnd=1000, card_token=tok), 1.7e9, None, "HUMAN", "ATM_SWITCH")        # nguồn ATM không gửi loại này


def test_readiness_flags_new_ai_components(monkeypatch):
    monkeypatch.setenv("DEPLOY_PROFILE", "production")
    ids = {c["id"]: c for c in profiles.readiness()}
    assert ids["AI_ENSEMBLE_REAL_DATA"]["level"] == "BLOCKER" and ids["FACE_AI_PROVIDER"]["level"] == "BLOCKER" and ids["AI_ENSEMBLE_SHADOW"]["ok"]
