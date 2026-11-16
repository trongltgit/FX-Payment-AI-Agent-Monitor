import os
import re
import sys

# Cấu hình TRƯỚC khi import app (mock_db đọc env lúc import)
os.environ.update(
    PRICING_ENVIRONMENT="demo",
    SECRET_KEY="t" * 48,
    API_SIGNING_SECRET="s" * 48,
    DEMO_PASSWORD="demo-pass-12345",
    LOGIN_POW_BITS="8",
    LOGIN_MIN_FORM_SECONDS="0",
    LOGIN_FAIL_DELAY="0",
    TOTP_SECRET_HQ01="JBSWY3DPEHPK3PXP",
    SESSION_COOKIE_SECURE="0",
    AGENTMON_DB="/tmp/agentmon_test.db",
    LLM_PROVIDER="mock",
)
os.environ.pop("REDIS_URL", None)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from app import create_app  # noqa: E402
from utils import pow as pow_mod  # noqa: E402
from utils import store  # noqa: E402

PW = "demo-pass-12345"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
BROWSER = {
    "User-Agent": UA,
    "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Dest": "empty",
}


class Clock:
    def __init__(self):
        import time
        self.t = time.time()

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture(autouse=True)
def clean_store():
    store.set_client(None)
    store.reset_memory()
    import services.audit_log as al
    al._LOGS.clear()
    yield
    store.reset_memory()


@pytest.fixture
def clock(monkeypatch):
    c = Clock()
    monkeypatch.setattr(store, "now", c)
    return c


@pytest.fixture
def app():
    a = create_app()
    a.config["TESTING"] = True
    a.limiter.enabled = False
    return a


@pytest.fixture
def client(app):
    return app.test_client()


def get_form_token(c):
    html = c.get("/", headers=BROWSER).get_data(as_text=True)
    return re.search(r'formToken:\s*"([^"]+)"', html).group(1)


def solve_challenge(c, extra_bits=0):
    ch = c.get("/api/auth/challenge", headers=BROWSER).get_json()["challenge"]
    return {"challenge_id": ch["challenge_id"], "nonce": pow_mod.solve(ch["prefix"], ch["bits"])}


def login(c, user, password=PW, otp=None, hs=None, **override):
    body = {
        "username": user, "password": password,
        "form_token": get_form_token(c), "pow": solve_challenge(c), "website": "",
        "hs": hs if hs is not None else {"webdriver": False, "keys": 12, "moves": 30},
    }
    if otp:
        body["otp"] = otp
    body.update(override)
    r = c.post("/api/auth/login", json=body, headers=BROWSER)
    return r


def login_ok(c, user, **kw):
    r = login(c, user, **kw)
    assert r.status_code == 200, r.get_json()
    return r.get_json()["csrf_token"]


def post(c, path, token, json_body, extra=None):
    h = dict(BROWSER)
    h["X-CSRF-Token"] = token
    if extra:
        h.update(extra)
    return c.post(path, json=json_body, headers=h)


def setup_preset(app, cid="CUST001", staff="staff01", ccy="USD", side="SELL", margin=5):
    s = app.test_client()
    t = login_ok(s, staff)
    r = post(s, "/api/cn/margin-preset", t, {"customer_id": cid, "currency": ccy, "side": side, "margin": margin})
    assert r.status_code == 200, r.get_json()
    return s
