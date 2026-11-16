"""FX và thanh toán của CÙNG khách đến đồng thời ở HAI TIẾN TRÌNH khác nhau (như gunicorn -w 2):
số dư dùng chung không được vượt, không được thực hiện cả hai."""
import json
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

WORKER = textwrap.dedent("""
    import json, sys
    sys.path.insert(0, %r)
    from app import create_app
    create_app()
    from agentmon import engine, lab
    cid = "CUST001"
    if sys.argv[1] == "fx":
        u = lab._usual(cid, "FX")
        r = engine.evaluate(dict(domain="FX", kind="FX_TRADE", pair=u["pair"], side="BUY", notional_usd=28_000_000 / 26200, leverage=1),
                            lab._agent_for(cid, "FX"), source="LAB", customer_hint=cid, sim_hour=u["hour"])
    else:
        u = lab._usual(cid, "PAY")
        r = engine.evaluate(dict(domain="PAY", kind="TRANSFER", amount_vnd=28_000_000, beneficiary_account=u["ben"]),
                            lab._agent_for(cid, "PAY"), source="LAB", customer_hint=cid, sim_hour=u["hour"])
    print(json.dumps({"decision": r["decision"], "status": r["status"]}))
""" % ROOT)


def test_two_processes_share_balance_atomically(tmp_path):
    dbp = str(tmp_path / "mp.db")
    env = dict(os.environ, AGENTMON_DB=dbp, PRICING_ENVIRONMENT="demo", SECRET_KEY="t" * 48, API_SIGNING_SECRET="s" * 48,
               DEMO_PASSWORD="demo-pass-12345", LLM_PROVIDER="mock", PYTHONWARNINGS="ignore")
    env.pop("REDIS_URL", None)
    script = tmp_path / "w.py"
    script.write_text(WORKER)
    prep = subprocess.run([sys.executable, "-c", f"import sys;sys.path.insert(0,{ROOT!r});from app import create_app;create_app();"
                           "from agentmon import db,seed,lab;db.init();seed.seed(force=True)"], env=env, capture_output=True, text=True)
    assert prep.returncode == 0, prep.stderr[-400:]
    for _ in range(3):
        subprocess.run([sys.executable, "-c", f"import sys;sys.path.insert(0,{ROOT!r});from app import create_app;create_app();"
                        "from agentmon import lab;lab.prepare('CUST001');lab._set_balance('CUST001',30_000_000)"], env=env, check=True, capture_output=True)
        ps = [subprocess.Popen([sys.executable, str(script), k], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) for k in ("fx", "pay")]
        res = [json.loads(p.communicate()[0].strip().splitlines()[-1]) for p in ps]
        out = subprocess.run([sys.executable, "-c", f"import sys;sys.path.insert(0,{ROOT!r});from app import create_app;create_app();"
                              "from agentmon import db;print(db.one(\"select balance_vnd b from accounts where customer_id='CUST001'\")['b'])"],
                             env=env, capture_output=True, text=True, check=True)
        bal = float(out.stdout.strip().splitlines()[-1])
        assert bal >= 0
        assert sum(1 for r in res if r["status"] == "EXECUTED") <= 1, res
        assert sum(1 for r in res if r["status"] in ("PENDING_KYA", "EXECUTED")) == 1, res     # đúng một lệnh giữ được số dư
