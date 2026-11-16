"""Test phần mở rộng v1.1: kênh ATM/ví/Digibank-Digibiz, phân loại gian lận, trace giải trình, phiên bản mô hình,
dữ liệu thật/backtest, đóng gói và xử lý đồng thời FX + thanh toán."""
import csv
import random
import sqlite3
import threading

import pytest

from agentmon import catalog, db, dataio, engine, features as F, fraud_types, lab, ml, seed
from tests.conftest import BROWSER, login_ok, post


@pytest.fixture(autouse=True)
def reseed():
    db.init()
    seed.seed(force=True)
    yield


def run(sid, cid="CUST001"):
    r = lab.run(sid, cid)
    assert "steps" in r, r
    return r["steps"]


def last_trace(aid):
    return db.jload(db.one("SELECT details FROM actions WHERE id=?", (aid,))["details"], {}).get("trace")


# ---------------------------------------------------------------- kênh mới
def test_atm_normal_allow_and_limit_block():
    s17 = run("PAY-17")[0]                                  # AI Agent rút ATM → bắt buộc chủ thẻ xác nhận (v2.1)
    assert s17["decision"] == "KYA" and "AGENT_CASH_OUT" in s17["fraud_types"]
    s = run("PAY-18")[0]
    assert s["decision"] == "BLOCK" and "ATM" in s["reason"]


def test_atm_abroad_night_is_flagged_as_cashout_abroad():
    s = run("PAY-19")[0]
    assert s["decision"] in ("KYA", "REVIEW")
    assert "ATM_CASHOUT_ABROAD" in s["fraud_types"] and s["fraud_class"] == "FRAUD_SUSPECTED"


def test_wallet_new_device_kya_known_device_allow():
    assert run("PAY-21")[0]["decision"] == "ALLOW"
    s = run("PAY-20")[0]
    assert s["decision"] == "KYA" and any("thiết bị" in t.lower() for t in s["triggers"])
    assert "WALLET_DEVICE_ABUSE" in s["fraud_types"]


def test_digibank_digibiz_bill_and_qr():
    assert run("PAY-22")[0]["decision"] == "ALLOW"
    assert run("PAY-22", "CUST002")[0]["decision"] == "ALLOW"          # Digibiz doanh nghiệp
    assert run("PAY-23")[0]["decision"] in ("KYA", "REVIEW")
    g = run("PAY-24")[0]
    assert g["decision"] == "BLOCK" and "ILLEGAL_GAMBLING" in g["fraud_types"]


def test_fictitious_payment_pattern_detected():
    steps = run("PAY-25")
    assert all(s["decision"] != "ALLOW" for s in steps)
    assert "FICTITIOUS_PAYMENT" in steps[-1]["fraud_types"]


def test_normalize_rejects_bad_channel_and_missing_fields():
    n = lambda **k: engine.normalize(dict(domain="PAY", amount_vnd=1000, card_token="tok_x", merchant_id="M1", mcc="5411", **k), 1.7e9, None)
    with pytest.raises(engine.BadRequest):
        n(kind="ATM_WITHDRAWAL", channel_type="POS")
    with pytest.raises(engine.BadRequest):
        n(kind="WALLET_PAYMENT", wallet_provider="APPLE_PAY")                 # thiếu device_id
    with pytest.raises(engine.BadRequest):
        n(kind="WALLET_PAYMENT", wallet_provider="NOPE", device_id="DEV-123456")
    with pytest.raises(engine.BadRequest):
        n(kind="BILL_PAYMENT", channel_type="CNP")
    a = n(kind="QR_PAYMENT", channel_type="DIGIBIZ")
    assert a["channel_type"] == "DIGIBIZ"


# ---------------------------------------------------------------- phân loại gian lận
def test_card_testing_and_gambling_typology():
    s = run("PAY-12")
    assert s[-1]["fraud_class"] == "FRAUD_SUSPECTED" and "CARD_TESTING" in s[-1]["fraud_types"]
    assert "ILLEGAL_GAMBLING" in run("PAY-10")[0]["fraud_types"]


def test_benign_anomaly_is_not_labelled_fraud():
    s = run("PAY-05")[0]                      # người nhận mới số tiền lớn → KYA, chưa phải gian lận
    assert s["decision"] == "KYA" and s["fraud_class"] == "ANOMALY_UNCONFIRMED" and not s["fraud_types"]
    assert run("PAY-01")[0]["fraud_class"] == "NORMAL"


def test_taxonomy_has_stable_unique_codes():
    assert len(fraud_types.TAXONOMY) >= 15
    assert all(m["sev"] in ("HIGH", "MED") for m in fraud_types.TAXONOMY.values())


# ---------------------------------------------------------------- giải trình
def test_trace_complete_and_hash_detects_tampering():
    s = run("PAY-19")[0]
    row = db.one("SELECT * FROM actions WHERE id=?", (s["action_id"],))
    tr = last_trace(s["action_id"])
    for k in ("model", "scoring", "features", "limits_effective", "decision_path", "triggers", "fraud", "baseline", "context"):
        assert k in tr, k
    assert tr["model"]["version"].startswith("pay-iforest-") and len(tr["model"]["sha256"]) == 64
    assert tr["scoring"]["thresholds"]["kya"] and tr["scoring"]["weights"]["ml"] == F.W_ML
    assert set(tr["features"]) == set(F.COLS["PAY"])
    assert engine.trace_hash(tr) == row["trace_hash"] and row["model_version"] == tr["model"]["version"]
    tr["scoring"]["components"]["final"] = 0.01
    assert engine.trace_hash(tr) != row["trace_hash"]


def test_hard_block_trace_records_no_model_use_and_has_no_pan():
    s = run("PAY-08")[0]
    row = db.one("SELECT * FROM actions WHERE id=?", (s["action_id"],))
    tr = last_trace(s["action_id"])
    assert row["decision"] == "BLOCK" and row["model_version"] is None and tr["model"]["used_for_this_decision"] is False
    assert "4111111111111111" not in str(row) and "PCI_EXPOSURE" in db.jload(row["fraud_types"], [])


def test_explain_api_staff_only_and_integrity(app):
    s = run("PAY-19")[0]
    st = app.test_client(); login_ok(st, "staff01")
    r = st.get(f"/api/agent/actions/{s['action_id']}/explain", headers=BROWSER)
    d = r.get_json()
    assert r.status_code == 200 and d["integrity_ok"] and d["trace"]["model"]["version"]
    cu = app.test_client(); login_ok(cu, "cust001")
    assert cu.get(f"/api/agent/actions/{s['action_id']}/explain", headers=BROWSER).status_code in (401, 403)
    v = cu.get(f"/api/agent/actions/{s['action_id']}", headers=BROWSER).get_json()["action"]
    assert "fraud_class" not in v and "trace_hash" not in v and "anomaly" not in v        # khách không thấy nội bộ


# ---------------------------------------------------------------- mô hình
def test_model_manifest_versions_and_integrity():
    m = ml.read_manifest()
    for d in ("FX", "PAY"):
        cur = m[d]["current"]
        ent = [e for e in m[d]["history"] if e["version"] == cur][0]
        assert ent["sha256"] and ent["holdout"]["n"] > 0 and ent["data_source"].startswith("synthetic")
        assert ml.integrity(d)["ok"] and ml.model_ref(d)["version"] == cur
        assert ml.status()[d]["features"] == F.COLS[d]


def test_feature_catalog_covers_every_column_and_blend_is_single_source():
    for d, cols in F.COLS.items():
        assert not [c for c in cols if c not in catalog.FEATURES]
    assert abs(F.blend(0.5, 0.2, 0.1) - (0.7 * (0.4 * .5 + 0.3 * .2 + 0.3 * .1) + 0.3 * 0.2)) < 1e-9
    assert F.blend(0.5, 0.2, 0.1, True) > F.blend(0.5, 0.2, 0.1)


def test_old_database_is_migrated(tmp_path, monkeypatch):
    p = tmp_path / "old.db"
    old_schema = db.SCHEMA.replace(",\n  channel_type TEXT, device_id TEXT, fraud_class TEXT, fraud_types TEXT, model_version TEXT, trace_hash TEXT", "")
    assert old_schema != db.SCHEMA
    c = sqlite3.connect(p)
    c.executescript(old_schema)          # CSDL phiên bản 1.0 (chưa có 6 cột mới) và đã có dữ liệu
    c.execute("INSERT INTO actions(ts,domain,kind,customer_id,decision,status,reason_public) VALUES(1,'PAY','TRANSFER','C1','ALLOW','EXECUTED','x')")
    c.commit(); c.close()
    old = db._ready_path
    monkeypatch.setenv("AGENTMON_DB", str(p))
    try:
        db._ready_path = None
        db.init()
        cols = {r[1] for r in sqlite3.connect(p).execute("PRAGMA table_info(actions)")}
        assert {"channel_type", "device_id", "fraud_class", "fraud_types", "model_version", "trace_hash"} <= cols
        assert sqlite3.connect(p).execute("SELECT COUNT(*) FROM actions").fetchone()[0] == 1          # dữ liệu cũ còn nguyên
    finally:
        monkeypatch.undo()
        db._ready_path = None


# ---------------------------------------------------------------- dữ liệu thật + backtest
def _write_csv(path, n_cust=12, per=60, seed_=3):
    rng = random.Random(seed_)
    rows = []
    t0 = 1_760_000_000
    for c in range(n_cust):
        mean = rng.uniform(1e6, 6e6)
        t = t0
        for i in range(per):
            t += rng.uniform(3600, 86400)
            fraud = i > 20 and rng.random() < 0.06
            amt = mean * (rng.uniform(6, 12) if fraud else rng.lognormvariate(0, 0.3))
            rows.append(dict(txn_id=f"T{c}-{i}", customer_id=f"C{c}", ts=int(t - (t % 86400) + (3 * 3600 if fraud else 10 * 3600)), domain="PAY",
                             kind="TRANSFER", amount_vnd=round(amt, -3), channel_type="", beneficiary_account=("9" * 10) if fraud else f"123456789{c % 3}",
                             merchant_id="", mcc="", country="", three_ds="", device_id="", segment="STANDARD", balance_vnd=2e9,
                             fraud_label=1 if fraud else 0, label_source="fraud_case" if fraud else ""))
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=dataio.PAY_COLS)
        w.writeheader(); w.writerows(rows)
    rows.append({})
    return len(rows) - 1


def test_csv_load_validation_and_backtest(tmp_path, monkeypatch):
    p = tmp_path / "t.csv"
    n = _write_csv(p)
    txns, rep = dataio.load_csv(p, "PAY")
    assert rep["rows"] == n and rep["customers"] == 12 and rep["positives"] > 0 and rep["skipped"] == 0
    bad = tmp_path / "bad.csv"
    bad.write_text("txn_id,customer_id,ts,domain,kind,amount_vnd\nX,C1,not-a-date,PAY,TRANSFER,1000\nY,C1,1760000000,PAY,NOPE,1000\n")
    _, r2 = dataio.load_csv(bad, "PAY")
    assert r2["rows"] == 0 and r2["skipped"] == 2
    nocol = tmp_path / "nocol.csv"
    nocol.write_text("txn_id,customer_id\nA,B\n")
    with pytest.raises(dataio.DataError):
        dataio.load_csv(nocol, "PAY")
    from agentmon import backtest
    monkeypatch.setattr(backtest, "OUT", str(tmp_path))
    monkeypatch.setenv("AGENTMON_MODEL_DIR", str(tmp_path / "m"))
    res = backtest.run("PAY", csv_path=str(p))
    assert res["mode"] == "real-data" and res["test"]["n"] > 100 and "KYA_or_above" in res["test"]
    assert list(tmp_path.glob("backtest_PAY_*.md"))


def test_templates_are_loadable():
    for dom, f in (("PAY", "docs/templates/pay_transactions_template.csv"), ("FX", "docs/templates/fx_transactions_template.csv")):
        rows, rep = dataio.load_csv(f, dom)
        assert rep["rows"] == 3 and rep["positives"] == 1


# ---------------------------------------------------------------- FX + thanh toán đồng thời
def _fx(agent, usd):
    return dict(domain="FX", kind="FX_TRADE", pair="USDVND", side="BUY", notional_usd=usd, leverage=1)


def test_concurrent_fx_and_payment_cannot_overspend_shared_balance():
    cid = "CUST001"
    lab.prepare(cid)
    lab._set_balance(cid, 30_000_000)                         # chỉ đủ cho MỘT trong hai lệnh
    u_fx = lab._usual(cid, "FX")
    ag_fx, ag_pay = lab._agent_for(cid, "FX"), lab._agent_for(cid, "PAY")
    usd = 28_000_000 / 26200 / 1.0
    out, errs = {}, []

    def do_fx():
        try:
            out["fx"] = engine.evaluate(dict(domain="FX", kind="FX_TRADE", pair=u_fx["pair"], side="BUY", notional_usd=usd, leverage=1),
                                        ag_fx, source="LAB", customer_hint=cid, sim_hour=u_fx["hour"])
        except Exception as e:      # noqa: BLE001
            errs.append(e)

    def do_pay():
        try:
            u = lab._usual(cid, "PAY")
            out["pay"] = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=28_000_000, beneficiary_account=u["ben"]),
                                         ag_pay, source="LAB", customer_hint=cid, sim_hour=u["hour"])
        except Exception as e:      # noqa: BLE001
            errs.append(e)

    ts = [threading.Thread(target=f) for f in (do_fx, do_pay)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert not errs, errs
    bal = db.one("SELECT balance_vnd b FROM accounts WHERE customer_id=?", (cid,))["b"]
    assert bal >= 0, bal                                              # không bao giờ âm
    executed = [k for k, v in out.items() if v["status"] == "EXECUTED"]
    assert len(executed) <= 1, {k: (v["decision"], v["status"]) for k, v in out.items()}


def test_cross_domain_burst_raises_velocity_and_typology():
    cid = "CUST005"
    lab.prepare(cid)
    ag_fx, ag_pay = lab._agent_for(cid, "FX"), lab._agent_for(cid, "PAY")
    u_fx, u_pay = lab._usual(cid, "FX"), lab._usual(cid, "PAY")
    now = engine.store.now()
    last = None
    for i in range(5):
        engine.evaluate(dict(domain="FX", kind="FX_TRADE", pair=u_fx["pair"], side="BUY", notional_usd=u_fx["amt"], leverage=1),
                        ag_fx, source="LAB", customer_hint=cid, sim_hour=u_fx["hour"], sim_ts=now - 200 + i * 10)
    last = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=u_pay["tamt"], beneficiary_account=u_pay["ben"]),
                           ag_pay, source="LAB", customer_hint=cid, sim_hour=u_pay["hour"], sim_ts=now - 100)
    tr = db.jload(db.one("SELECT details FROM actions WHERE id=?", (last["action_id"],))["details"], {})["trace"]
    assert tr["context"]["cross_domain_n5"] >= 4
    assert "CROSS_DOMAIN_BURST" in last["fraud_types"]
