"""Bộ kiểm thử lớp chống bot v2 – mỗi test mô phỏng 1 kiểu tấn công / 1 cơ chế bảo vệ."""
import base64
import hashlib
import hmac
import json
import time

import pytest

from services import bot_defense
from services.audit_log import list_logs
from utils import store, totp
from tests.conftest import BROWSER, PW, UA, login, login_ok, post, setup_preset


# ============================================================ 1. UA / header / IP
@pytest.mark.parametrize("ua", ["curl/8.0", "python-requests/2.31", "Scrapy/2.0", "HeadlessChrome/120", ""])
def test_ua_tool_blocked(client, ua):
    r = client.get("/api/public-data", headers={"User-Agent": ua})
    assert r.status_code == 403 and r.get_json()["error"] == "CRAWL_BLOCKED"


def test_repeated_bad_ua_gets_ip_banned(client):
    codes = [client.get("/api/public-data", headers={"User-Agent": "curl/8.0"}).get_json()["error"] for _ in range(6)]
    assert codes[0] == "CRAWL_BLOCKED" and codes[-1] == "IP_BANNED"


def test_chrome_ua_without_browser_headers_blocked(client):
    """Script giả UA Chrome nhưng thiếu Accept-Language / Sec-Fetch-* -> bị lộ."""
    r = client.get("/api/public-data", headers={"User-Agent": UA})
    assert r.status_code == 403 and r.get_json()["error"] == "BROWSER_PROFILE_MISMATCH"


def test_ip_header_spoof_ignored(client, monkeypatch):
    # CF-Connecting-IP chỉ được tin khi TRUSTED_PROXY=cloudflare (v1 tin nếu có CF-Ray -> giả IP được)
    client.get("/api/public-data", headers={"User-Agent": "curl/8", "CF-Ray": "x", "CF-Connecting-IP": "1.2.3.4"})
    assert [x["ip"] for x in list_logs() if x["event"] == "crawl_attempt"] == ["127.0.0.1"]
    # Không đứng sau proxy (PROXY_HOPS=0) thì X-Forwarded-For của client cũng bị bỏ qua
    monkeypatch.setenv("PROXY_HOPS", "0")
    from app import create_app
    a = create_app(); a.limiter.enabled = False
    store.reset_memory()
    a.test_client().get("/api/public-data", headers={"User-Agent": "curl/8", "X-Forwarded-For": "5.6.7.8"})
    assert "5.6.7.8" not in [x["ip"] for x in list_logs()]
    # Đứng sau Cloudflare thật: đặt TRUSTED_PROXY -> lấy IP khách từ CF-Connecting-IP
    monkeypatch.setenv("TRUSTED_PROXY", "cloudflare")
    store.reset_memory(); list_logs()
    a.test_client().get("/api/public-data", headers={"User-Agent": "curl/9", "CF-Connecting-IP": "8.8.4.4"})
    assert "8.8.4.4" in [x["ip"] for x in list_logs()]


def test_audit_log_flood_is_throttled(client):
    for _ in range(300):
        client.get("/api/public-data", headers={"User-Agent": "curl/8"})
    n = len([x for x in list_logs() if x["event"] == "crawl_attempt"])
    assert n <= 5      # bot không thể làm ngập / đẩy trôi log của người khác


def test_honeypot_bans_ip(client):
    r = client.get("/api/internal/rates-export", headers=BROWSER)
    assert r.status_code == 404
    r2 = client.get("/api/health", headers=BROWSER)   # health vẫn mở
    r3 = client.get("/api/auth/me", headers=BROWSER)
    assert r3.status_code == 403 and r3.get_json()["error"] == "IP_BANNED"
    assert any(x["event"] == "honeypot_hit" for x in list_logs())


def test_robots_lists_trap_paths(client):
    body = client.get("/robots.txt").get_data(as_text=True)
    assert "/api/internal/" in body and "/api/v1/" in body


def test_security_headers(client):
    r = client.get("/", headers=BROWSER)
    for h in ["Content-Security-Policy", "X-Frame-Options", "X-Content-Type-Options", "Referrer-Policy"]:
        assert h in r.headers
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]
    assert client.get("/api/health", headers=BROWSER).headers["Cache-Control"] == "no-store"


def test_sign_helper_removed(client):
    assert client.post("/api/sign-helper", headers=BROWSER).status_code in (401, 403, 410)


# ============================================================ 2. Đăng nhập
def test_login_needs_form_token_and_pow(client):
    base = {"username": "cust001", "password": PW}
    r = client.post("/api/auth/login", json=base, headers=BROWSER)
    assert r.get_json()["error"] == "FORM_TOKEN_INVALID"
    from tests.conftest import get_form_token, solve_challenge
    r = client.post("/api/auth/login", json={**base, "form_token": get_form_token(client)}, headers=BROWSER)
    assert r.get_json()["error"] == "POW_REQUIRED"
    # PoW sai
    ch = client.get("/api/auth/challenge", headers=BROWSER).get_json()["challenge"]
    r = client.post("/api/auth/login", json={**base, "form_token": get_form_token(client),
                    "pow": {"challenge_id": ch["challenge_id"], "nonce": -1}}, headers=BROWSER)
    assert r.get_json()["error"] == "POW_REQUIRED"


def test_pow_and_form_token_are_single_use(client):
    from tests.conftest import get_form_token, solve_challenge
    ft, pw_ = get_form_token(client), solve_challenge(client)
    body = {"username": "cust001", "password": "sai", "form_token": ft, "pow": pw_, "website": "",
            "hs": {"keys": 3, "moves": 3}}
    assert client.post("/api/auth/login", json=body, headers=BROWSER).get_json()["error"] == "INVALID_CREDENTIALS"
    r = client.post("/api/auth/login", json=body, headers=BROWSER)      # replay y nguyên
    assert r.get_json()["error"] in {"FORM_TOKEN_INVALID", "POW_REQUIRED"}


def test_login_honeypot_field(client):
    r = login(client, "cust001", website="http://spam")
    assert r.status_code == 403


def test_login_webdriver_blocked(client):
    r = login(client, "cust001", hs={"webdriver": True, "keys": 1, "moves": 1})
    assert r.status_code == 403 and r.get_json()["error"] == "AUTOMATION_DETECTED"


def test_session_cookie_contains_no_data(client):
    login_ok(client, "staff01")
    raw = client.get_cookie("ab_sid").value
    decoded = base64.urlsafe_b64decode(raw.split(".")[0] + "==").decode(errors="ignore")
    assert "staff01" not in raw and "PNV" not in decoded and "CUST001" not in decoded


def test_passwords_are_hashed():
    from app.customer.mock_db import DEMO_USERS
    for u in DEMO_USERS.values():
        assert "password" not in u and u["password_hash"].startswith(("scrypt:", "pbkdf2:"))


def test_bruteforce_lockout(client):
    for i in range(5):
        assert login(client, "hq01", password=f"sai{i}").status_code in (401,)
    r = login(client, "hq01")                       # đúng mật khẩu nhưng đã bị khóa tạm
    assert r.status_code == 429 and r.get_json()["error"] == "TOO_MANY_ATTEMPTS"


def test_credential_stuffing_locks_ip(client):
    for i in range(20):
        login(client, f"user{i}", password="x")
    r = login(client, "cust001")
    assert r.status_code == 429


def test_mfa_flow_and_otp_replay(client, monkeypatch):
    monkeypatch.setenv("MFA_REQUIRED_ROLES", "HQ")
    r = login(client, "hq01")
    assert r.status_code == 401 and r.get_json()["error"] == "MFA_REQUIRED"
    assert login(client, "hq01", otp="000000").status_code == 401
    code = totp.totp_now("JBSWY3DPEHPK3PXP")
    assert login(client, "hq01", otp=code).status_code == 200
    c2 = client.application.test_client()
    assert login(c2, "hq01", otp=code).status_code == 401          # OTP đã dùng


# ============================================================ 3. Session / CSRF
def test_csrf_enforced_on_every_write_route(client):
    t = login_ok(client, "hq01")
    r = client.post("/api/hq/blocked/lock", json={"user_id": "cust003"}, headers=BROWSER)
    assert r.status_code == 403 and r.get_json()["error"] == "CSRF_INVALID"
    assert post(client, "/api/hq/blocked/lock", t, {"user_id": "cust003"}).status_code == 200


def test_cross_origin_write_rejected(client):
    t = login_ok(client, "hq01")
    r = post(client, "/api/hq/blocked/lock", t, {"user_id": "cust003"}, {"Origin": "https://evil.example"})
    assert r.status_code == 403 and r.get_json()["error"] == "CSRF_ORIGIN"
    r = post(client, "/api/hq/blocked/lock", t, {"user_id": "cust003"}, {"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403


def test_logout_revokes_old_cookie(client):
    t = login_ok(client, "cust001")
    old = client.get_cookie("ab_sid").value
    assert post(client, "/api/auth/logout", t, {}).status_code == 200
    c2 = client.application.test_client()
    c2.set_cookie("ab_sid", old)
    assert c2.get("/api/auth/me", headers=BROWSER).status_code == 401


def test_forged_cookie_is_useless(app):
    from itsdangerous import URLSafeSerializer
    ser = URLSafeSerializer(app.secret_key, salt="ab-sid")
    c = app.test_client()
    c.set_cookie("ab_sid", ser.dumps("sid-do-attacker-tu-che"))
    assert c.get("/api/auth/me", headers=BROWSER).status_code == 401
    c.set_cookie("ab_sid", "payload-bat-ky.chuky")
    assert c.get("/api/auth/me", headers=BROWSER).status_code == 401


def test_session_fixation_new_sid_after_login(client):
    client.get("/", headers=BROWSER)
    login_ok(client, "cust001")
    sid1 = client.get_cookie("ab_sid").value
    login_ok(client, "cust001")
    assert client.get_cookie("ab_sid").value != sid1


def test_locked_user_old_cookie_dead(app):
    cust = app.test_client()
    login_ok(cust, "cust001")
    old = cust.get_cookie("ab_sid").value
    hq = app.test_client()
    t = login_ok(hq, "hq01")
    assert post(hq, "/api/hq/blocked/lock", t, {"user_id": "cust001"}).status_code == 200
    c2 = app.test_client()
    c2.set_cookie("ab_sid", old)
    assert c2.get("/api/auth/me", headers=BROWSER).status_code in (401, 403)
    assert login(app.test_client(), "cust001").status_code == 403


def test_single_session_for_customers(app):
    a, b = app.test_client(), app.test_client()
    login_ok(a, "cust001")
    login_ok(b, "cust001")
    assert a.get("/api/auth/me", headers=BROWSER).status_code == 401      # phiên cũ bị thu hồi
    assert b.get("/api/auth/me", headers=BROWSER).status_code == 200


def test_fingerprint_change_kills_session(client):
    login_ok(client, "cust001")
    h = dict(BROWSER)
    h["Accept-Language"] = "ru-RU"
    r = client.get("/api/auth/me", headers=h)
    assert r.status_code == 403 and r.get_json()["error"] == "INVALID_SESSION"
    assert client.get("/api/auth/me", headers=BROWSER).status_code == 401


def test_permission_change_takes_effect_immediately(app):
    s = app.test_client()
    login_ok(s, "staff01")
    assert "CUST001" in s.get("/api/customers/permitted", headers=BROWSER).get_json()["customers"][0]["customer_id"]
    from app.customer import mock_db
    mock_db.DEMO_USERS["staff01"]["permitted_customers"] = ["CUST003"]
    try:
        ids = [c["customer_id"] for c in s.get("/api/customers/permitted", headers=BROWSER).get_json()["customers"]]
        assert ids == ["CUST003"]
    finally:
        mock_db.DEMO_USERS["staff01"]["permitted_customers"] = ["CUST001", "CUST003"]


def test_per_user_request_budget(client):
    login_ok(client, "cust001")
    codes = [client.get("/api/auth/me", headers=BROWSER).status_code for _ in range(70)]
    assert codes.count(429) >= 5 and codes[0] == 200


# ============================================================ 4. Báo giá / giao dịch
def _quote(c, t, amt=1000, ccy="USD", side="SELL", extra=None, **kw):
    return post(c, "/api/transaction/quote", t, {"currency": ccy, "side": side, "amount": amt, **kw}, extra)


def test_quote_response_hides_internals(app):
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    q = _quote(c, t).get_json()["quote"]
    assert set(q) == {"quote_id", "currency", "side", "price", "amount", "valid_for_seconds", "issued_at"}
    s = app.test_client(); ts = login_ok(s, "staff01")
    qs = _quote(s, ts, customer_id="CUST001", branch_margin=3).get_json()["quote"]
    assert "base_price" not in qs and "hq_base_spread" not in qs
    h = app.test_client(); th = login_ok(h, "hq01")
    qh = _quote(h, th, customer_id="CUST001", branch_margin=3).get_json()["quote"]
    assert "base_price" in qh


def test_customer_id_never_trusted_from_body(app):
    setup_preset(app); setup_preset(app, cid="CUST002", staff="staff03")
    c = app.test_client(); t = login_ok(c, "cust001")
    assert _quote(c, t, customer_id="CUST002").status_code == 200
    logs = [x for x in list_logs() if x["event"] == "quote_request" and x["user_id"] == "cust001"]
    assert logs[-1]["customer_id"] == "CUST001"


def test_quote_lives_on_server_not_cookie(app):
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    qid = _quote(c, t).get_json()["quote"]["quote_id"]
    assert qid not in c.get_cookie("ab_sid").value


def test_quote_single_use_and_session_bound(app):
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    qid = _quote(c, t).get_json()["quote"]["quote_id"]
    assert post(c, "/api/transaction/execute", t, {"quote_id": qid}).status_code == 200
    r = post(c, "/api/transaction/execute", t, {"quote_id": qid})
    assert r.status_code == 409 and r.get_json()["error"] == "QUOTE_ALREADY_USED"
    # quote của phiên khác (đăng nhập lại) không dùng lại được
    q2 = _quote(c, t, amt=2000).get_json()["quote"]["quote_id"]
    t2 = login_ok(c, "cust001")
    assert post(c, "/api/transaction/execute", t2, {"quote_id": q2}).get_json()["error"] == "INVALID_QUOTE"


def test_cooldown_uses_amount_bucket(app):
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    assert _quote(c, t, amt=1000).status_code == 200
    assert _quote(c, t, amt=1000.01).status_code == 429       # né bằng 0,01 không còn tác dụng
    assert _quote(c, t, amt=5000).status_code == 200          # nhu cầu thật (số tiền khác hẳn) vẫn được phục vụ


def test_soft_limit_revokes_session_for_real(app, clock):
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    old = c.get_cookie("ab_sid").value
    codes = []
    for k in range(8):
        clock.advance(2)
        codes.append(_quote(c, t, amt=1000 + 500 * k).status_code)
    assert codes[-1] == 401
    c2 = app.test_client(); c2.set_cookie("ab_sid", old)
    assert c2.get("/api/auth/me", headers=BROWSER).status_code == 401      # v1: vẫn 200


def test_repeated_soft_violations_lock_account(app, clock):
    setup_preset(app)
    for rnd in range(4):
        c = app.test_client()
        r = login(c, "cust001")
        if r.status_code != 200:
            break
        t = r.get_json()["csrf_token"]
        for k in range(8):
            clock.advance(1)
            _quote(c, t, amt=1000 + 700 * k + rnd)
    from app.customer.mock_db import is_user_blocked
    assert is_user_blocked("cust001")


def test_daily_quota(app, clock, monkeypatch):
    monkeypatch.setitem(bot_defense.PROFILES["CUSTOMER"], "per_day", 6)
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    codes = []
    for k in range(8):
        clock.advance(25 + k * 7)
        codes.append(_quote(c, t, amt=1000 + 900 * k).status_code)
    assert codes[:6] == [200] * 6 and codes[6] == 429


def test_quota_survives_log_ring_overflow(app, clock, monkeypatch):
    """v1/bản trước: quota ngày đếm từ vòng log 8000 dòng -> bot khác làm tràn log là reset quota."""
    from services.audit_log import add_log
    monkeypatch.setitem(bot_defense.PROFILES["CUSTOMER"], "per_day", 3)
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    for k in range(3):
        clock.advance(20 + k)
        assert _quote(c, t, amt=1000 + 900 * k).status_code == 200
    for _ in range(8100):
        add_log("noise", ip="9.9.9.9")
    clock.advance(30)
    assert _quote(c, t, amt=9000).status_code == 429


def test_metronome_bot_gets_challenged_then_pays_pow(app, clock):
    """Bot 'chậm mà đều' (3 lần/phút, dưới MỌI ngưỡng 60 giây của v1) vẫn bị bắt nhờ nhịp đều."""
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    amounts = [1000, 3000, 5000, 7000]                       # 4 tổ hợp luân phiên, mỗi tổ hợp cách nhau 80s (> cooldown)
    codes, challenge = [], None
    for k in range(12):
        clock.advance(20)
        r = _quote(c, t, amt=amounts[k % 4])
        codes.append(r.status_code)
        if r.status_code == 428:
            challenge = r.get_json()["challenge"]
            break
    assert codes[:9] == [200] * 9, codes            # 9 lần đầu chưa đủ dữ liệu để kết luận
    assert codes[-1] == 428 and challenge, codes    # lần thứ 10: nhịp quá đều -> bắt giải PoW
    from utils import pow as pow_mod
    nonce = pow_mod.solve(challenge["prefix"], challenge["bits"])
    r = _quote(c, t, amt=amounts[(len(codes) - 1) % 4],
               extra={"X-Challenge-Id": challenge["challenge_id"], "X-Challenge-Nonce": str(nonce)})
    assert r.status_code == 200                      # giải đúng PoW -> được phục vụ (chi phí CPU, không phải chặn tuyệt đối)
    r = _quote(c, t, amt=9000, extra={"X-Challenge-Id": challenge["challenge_id"], "X-Challenge-Nonce": str(nonce)})
    assert r.status_code in (428, 429)               # PoW đã dùng 1 lần, dùng lại không được


def test_amount_walk_enumeration_detected(app, clock):
    setup_preset(app)
    c = app.test_client(); t = login_ok(c, "cust001")
    gaps = [7, 13, 9, 17, 11, 8, 19, 12, 10, 15, 14, 9]            # nhịp không đều -> tránh metronome
    codes = []
    for k, g in enumerate(gaps):
        clock.advance(g)
        codes.append(_quote(c, t, amt=1000 + 1100 * k).status_code)
    assert any(x in (428, 429) for x in codes)


def test_multi_account_and_multi_ip_signals():
    for i in range(4):
        bot_defense.record_login(f"cust9{i}", "CUSTOMER", "10.0.0.1")
    d = bot_defense.assess("cust90", "CUSTOMER", "10.0.0.1")
    assert any("multi_account_ip" in r for r in d.reasons)
    for ip in ["1.1.1.1", "2.2.2.2", "3.3.3.3", "4.4.4.4"]:
        store.events_add("uip:bot1", ip)
    assert any("multi_ip" in r for r in bot_defense.assess("bot1", "CUSTOMER", "1.1.1.1").reasons)


def test_batch_consumes_quota(app, clock, monkeypatch):
    monkeypatch.setitem(bot_defense.PROFILES["STAFF"], "per_day", 60)
    s = app.test_client(); t = login_ok(s, "staff01")
    items = [{"customer_id": "CUST001", "currency": "USD", "side": "SELL", "amount": 1000 + i} for i in range(40)]
    assert post(s, "/api/transaction/quote-batch", t, {"items": items}).status_code == 200
    clock.advance(30)
    assert post(s, "/api/transaction/quote-batch", t, {"items": items}).status_code == 429
    too_many = [{"customer_id": "CUST001", "currency": "USD", "side": "SELL", "amount": 1}] * 51
    assert post(s, "/api/transaction/quote-batch", t, {"items": too_many}).status_code in (400, 429)


# ============================================================ 5. HMAC cho client tích hợp
def _sign(c, ts, nonce, body, path="/api/transaction/quote"):
    fp = hashlib.sha256(f"{UA}|{BROWSER['Accept-Language']}|".encode()).hexdigest()[:24]
    msg = f"{ts}:POST:{path}:{hashlib.sha256(body.encode()).hexdigest()}:127.0.0.1:{fp}:{nonce}"
    return hmac.new(b"s" * 48, msg.encode(), hashlib.sha256).hexdigest()


def test_hmac_requires_nonce_and_is_single_use(app):
    setup_preset(app)
    c = app.test_client(); login_ok(c, "cust001")
    body = json.dumps({"currency": "USD", "side": "SELL", "amount": 1000})
    ts = str(int(time.time()))

    def call(nonce, amt=None):
        b = body if amt is None else json.dumps({"currency": "USD", "side": "SELL", "amount": amt})
        h = {**BROWSER, "Content-Type": "application/json", "X-Timestamp": ts, "X-Nonce": nonce,
             "X-Signature": _sign(c, ts, nonce, b)}
        return c.post("/api/transaction/quote", data=b, headers=h)

    assert call("").status_code == 401                         # v1: thiếu nonce -> bỏ qua kiểm replay
    assert call("nonce-12345678").status_code == 200
    assert call("nonce-12345678").status_code == 401           # replay


# ============================================================ 6. Cấu hình / hạ tầng
def test_production_refuses_weak_config(monkeypatch):
    from app import create_app
    monkeypatch.setenv("PRICING_ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "short")
    monkeypatch.setenv("DEMO_PASSWORD", "demo123")
    with pytest.raises(RuntimeError) as e:
        create_app()
    assert "SECRET_KEY" in str(e.value) and "REDIS_URL" in str(e.value) and "DEMO_PASSWORD" in str(e.value)
    monkeypatch.setenv("SECRET_KEY", "k" * 40)
    monkeypatch.setenv("API_SIGNING_SECRET", "z" * 40)
    monkeypatch.setenv("ALLOW_MEMORY_STORE", "1")
    monkeypatch.setenv("DEMO_PASSWORD", "mat-khau-rat-dai-123")
    a = create_app()
    assert a.config["SESSION_COOKIE_SECURE"] is True
    assert "Strict-Transport-Security" in a.test_client().get("/", headers=BROWSER).headers


def test_store_works_identically_on_redis():
    fakeredis = pytest.importorskip("fakeredis")
    store.set_client(fakeredis.FakeRedis(decode_responses=True))
    assert store.backend() == "redis"
    assert store.setnx("k", "1", 30) and not store.setnx("k", "1", 30)
    assert store.incr("c", 30) == 1 and store.incr("c", 30) == 2
    store.events_add("ev", "a"); store.events_add("ev", "b"); store.events_add("ev", "a")
    assert store.events_count("ev", 60) == 3 and store.events_distinct("ev", 60) == 2
    assert 0 < store.ttl("k") <= 30
    store.set_json("j", {"x": 1}, ttl=10)
    assert store.get_json("j") == {"x": 1} and store.keys("j") == ["j"]


def test_full_stack_on_redis_session_and_ban(app):
    fakeredis = pytest.importorskip("fakeredis")
    store.set_client(fakeredis.FakeRedis(decode_responses=True))
    c = app.test_client()
    t = login_ok(c, "cust001")
    assert c.get("/api/auth/me", headers=BROWSER).status_code == 200
    post(c, "/api/auth/logout", t, {})
    assert c.get("/api/auth/me", headers=BROWSER).status_code == 401


def test_hq_security_summary(app):
    client = app.test_client()
    app.test_client().get("/api/internal/rates-export", headers={**BROWSER})   # tạo 1 vụ honeypot
    store.reset_memory()
    for _ in range(3):
        client.get("/api/public-data", headers={"User-Agent": "curl/8"})
    t = login_ok(client, "hq01")
    r = client.get("/api/hq/security-summary", headers=BROWSER).get_json()
    assert r["status"] == "success" and "events" in r and "banned_ips" in r
    cust = app.test_client(); login_ok(cust, "cust001")
    assert cust.get("/api/hq/security-summary", headers=BROWSER).status_code == 403


# ============================================================ 7. Giao diện
@pytest.mark.parametrize("path", ["/", "/login/hq", "/login/cn", "/login/kh", "/robots.txt", "/blocked"])
def test_public_pages_render(client, path):
    r = client.get(path, headers=BROWSER)
    assert r.status_code in (200, 403)
    if path.startswith("/login") or path == "/":
        html = r.get_data(as_text=True)
        assert "antibot.js" in html and "login.js" in html and 'id="website"' in html and "formToken" in html
        assert 'value="demo123"' not in html or path != "/"       # trang chủ không điền sẵn mật khẩu


@pytest.mark.parametrize("user,path", [("hq01", "/portal/hq"), ("staff01", "/portal/cn"),
                                       ("admin_cn01", "/portal/cn"), ("cust001", "/portal/kh")])
def test_portals_render_after_login(app, user, path):
    c = app.test_client()
    login_ok(c, user)
    r = c.get(path, headers=BROWSER)
    assert r.status_code == 200 and "antibot.js" in r.get_data(as_text=True)


def test_portal_needs_login_and_right_role(app):
    c = app.test_client()
    assert c.get("/portal/hq", headers=BROWSER).status_code == 302
    login_ok(c, "cust001")
    assert c.get("/portal/hq", headers=BROWSER).status_code == 403


def test_production_does_not_prefill_password(monkeypatch):
    monkeypatch.setenv("PRICING_ENVIRONMENT", "production")
    monkeypatch.setenv("SECRET_KEY", "k" * 40); monkeypatch.setenv("API_SIGNING_SECRET", "z" * 40)
    monkeypatch.setenv("ALLOW_MEMORY_STORE", "1"); monkeypatch.setenv("DEMO_PASSWORD", "mat-khau-rat-dai-123")
    from app import create_app
    html = create_app().test_client().get("/login/kh", headers=BROWSER).get_data(as_text=True)
    assert "demo123" not in html
