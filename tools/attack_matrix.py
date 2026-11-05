"""
Ma trận tấn công: chạy CÙNG một bộ kịch bản bot lên một phiên bản mã nguồn và in kết quả JSON.

    python tools/attack_matrix.py --root /đường/dẫn/anti-bot-pro-main

Kịch bản đặt ở góc nhìn kẻ tấn công: success=True nghĩa là cuộc tấn công THÀNH CÔNG.
Rate limit theo IP (Flask-Limiter) được tắt để cô lập logic ứng dụng; đồng hồ được giả lập
để chạy được kịch bản kéo dài nhiều giờ.
"""
import argparse, hashlib, json, os, random, re, sys, time

ap = argparse.ArgumentParser(); ap.add_argument("--root", required=True); args = ap.parse_args()
ROOT = os.path.abspath(args.root); sys.path.insert(0, ROOT)
V2 = os.path.exists(os.path.join(ROOT, "utils", "store.py"))

PW = "demo-pass-12345" if V2 else "demo123"
os.environ.update(SECRET_KEY="k" * 48, API_SIGNING_SECRET="s" * 48, SESSION_COOKIE_SECURE="0",
                  DEMO_PASSWORD="demo-pass-12345", LOGIN_POW_BITS="8", LOGIN_MIN_FORM_SECONDS="0", LOGIN_FAIL_DELAY="0")
os.environ.pop("REDIS_URL", None)

from app import create_app                                   # noqa: E402
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")
FULL = {"User-Agent": UA, "Accept-Language": "vi-VN,vi;q=0.9", "Accept-Encoding": "gzip, br",
        "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty"}
BARE = {"User-Agent": UA}                                    # script giả UA, quên các header còn lại

# ---- đồng hồ giả lập
_real = time.time
_clock = {"t": _real()}
def now(): return _clock["t"]
def advance(s): _clock["t"] += s
time.time = now
if V2:
    from utils import store, pow as pow_mod
    store.now = now

def fresh():
    """Trạng thái sạch giữa các kịch bản: không để khóa IP / cooldown / log của kịch bản trước ảnh hưởng kịch bản sau."""
    advance(7200)
    if V2:
        store.reset_memory()
    import services.audit_log as al
    al._LOGS.clear()
    for name in ("_QUOTE_COOLDOWN", "_USED_QUOTES"):
        getattr(al, name, {}).clear() if hasattr(al, name) else None
    try:
        import app.customer.mock_db as m
        getattr(m, "BLOCKED_USERS", {}).clear()
    except Exception:
        pass
    try:
        import utils.redis_store as rs
        rs._mem_blocked.clear(); rs._mem_used_quotes.clear()
    except Exception:
        pass
    try:
        import app.transaction as tr
        tr._TRANSACTIONS.clear()
    except Exception:
        pass

def new_app():
    fresh()
    a = create_app(); a.limiter.enabled = False
    return a

def login(c, user, pw=None, headers=FULL):
    pw = pw or PW
    body = {"username": user, "password": pw}
    if V2:
        html = c.get("/", headers=headers).get_data(as_text=True)
        m = re.search(r'formToken:\s*"([^"]+)"', html)
        body["form_token"] = m.group(1) if m else ""
        ch = c.get("/api/auth/challenge", headers=headers).get_json()
        if ch and "challenge" in ch:
            ch = ch["challenge"]
            body["pow"] = {"challenge_id": ch["challenge_id"], "nonce": pow_mod.solve(ch["prefix"], ch["bits"])}
        body["hs"] = {"webdriver": False, "keys": 9, "moves": 20}; body["website"] = ""
    r = c.post("/api/auth/login", json=body, headers=headers)
    j = r.get_json() or {}
    return r.status_code, j.get("csrf_token", ""), j

def post(c, path, tok, body, extra=None, headers=FULL):
    h = dict(headers); h["X-CSRF-Token"] = tok
    if extra: h.update(extra)
    return c.post(path, json=body, headers=h)

def cookie_name(a): return "ab_sid" if V2 else "session"
def setup_preset(app):
    s = app.test_client(); _, t, _ = login(s, "staff01")
    post(s, "/api/cn/margin-preset", t, {"customer_id": "CUST001", "currency": "USD", "side": "SELL", "margin": 5})

R = []
def rec(i, title, success, detail): R.append({"id": i, "title": title, "attack_succeeds": bool(success), "detail": detail})

# ---------------------------------------------------------------- kịch bản
app = new_app(); setup_preset(app)

# A1 script chỉ giả UA Chrome đăng nhập
c = app.test_client(); code, tok, j = login(c, "cust001", headers=BARE)
rec("A1", "Script giả UA Chrome (thiếu Sec-Fetch/Accept-Language) đăng nhập được", code == 200, f"HTTP {code} {j.get('error','')}")

# A2 bot bắt chước đủ header
c = app.test_client(); code, tok, j = login(c, "cust002")
rec("A2", "Bot bắt chước ĐỦ header trình duyệt + có tài khoản đăng nhập được", code == 200, f"HTTP {code} {j.get('error','')}")

# A3 dò mật khẩu: 12 lần sai rồi đúng
app = new_app()
c = app.test_client(); last = None
for i in range(12): login(c, "hq01", pw=f"sai-{i}")
code, _, j = login(c, "hq01")
rec("A3", "Dò mật khẩu hq01: 12 lần sai rồi nhập đúng vẫn vào được", code == 200, f"HTTP {code} {j.get('error','')}")

# A4 CSRF
app = new_app()
h = app.test_client(); _, th, _ = login(h, "hq01")
r = h.post("/api/hq/blocked/lock", json={"user_id": "cust003", "reason": "csrf"}, headers=FULL)   # KHÔNG có X-CSRF-Token
rec("A4", "CSRF: trang ngoài ép HQ khóa user (không có token)", r.status_code == 200, f"HTTP {r.status_code}")
try:
    from app.customer.mock_db import unlock_user; unlock_user("cust003")
except Exception: pass

# A5 cookie cũ sau khi người dùng ĐĂNG XUẤT / bị buộc đăng nhập lại
app = new_app(); setup_preset(app)
c = app.test_client(); _, t, _ = login(c, "cust001")
old = c.get_cookie(cookie_name(app)).value
post(c, "/api/auth/logout", t, {})
c2 = app.test_client(); c2.set_cookie(cookie_name(app), old)
me = c2.get("/api/auth/me", headers=FULL)
rec("A5", "Replay cookie cũ SAU KHI đăng xuất (cookie bị đánh cắp / bot giữ phiên) vẫn dùng được", me.status_code == 200,
    f"cookie cũ -> /api/auth/me HTTP {me.status_code}")

# A6 giả IP
app = new_app(); app.test_client().get("/api/public-data", headers={"User-Agent": "curl/8", "CF-Ray": "x", "CF-Connecting-IP": "1.2.3.4"})
from services.audit_log import list_logs
ips = [x["ip"] for x in list_logs() if x["event"] == "crawl_attempt"]
rec("A6", "Giả IP trong log bằng header CF-Connecting-IP", "1.2.3.4" in ips, f"IP ghi nhận: {ips[-1:] }")

# A7 cookie giả khi SECRET_KEY mặc định
saved = os.environ.pop("SECRET_KEY"); app = new_app(); os.environ["SECRET_KEY"] = saved
fp = hashlib.sha256(f"{UA}|{FULL['Accept-Language']}|".encode()).hexdigest()[:24]
from flask.sessions import SecureCookieSessionInterface
_k = app.secret_key
app.secret_key = "change-this-secret-key-in-production-32chars"       # khóa mặc định nằm công khai trong mã nguồn bản cũ
ser = SecureCookieSessionInterface().get_signing_serializer(app)
forged = ser.dumps({"user_id": "hq01", "role": "HQ", "fingerprint": fp, "permitted_customers": [], "csrf_token": "x"})
app.secret_key = _k
cc = app.test_client(); ok = False
cc.set_cookie("session", forged); cc.set_cookie("ab_sid", forged)
r = cc.get("/api/hq/users", headers=FULL); ok = r.status_code == 200; code = r.status_code
rec("A7", "Giả cookie HQ khi chủ hệ thống quên đặt SECRET_KEY (khóa mặc định trong mã)", ok, f"HTTP {code}")

# A8 replay execute
app = new_app(); setup_preset(app)
c = app.test_client(); _, t, _ = login(c, "cust001")
r = post(c, "/api/transaction/quote", t, {"currency": "USD", "side": "SELL", "amount": 1000}); qid = r.get_json()["quote"]["quote_id"]
okc = sum(1 for _ in range(5) if post(c, "/api/transaction/execute", t, {"quote_id": qid}).status_code == 200)
rec("A8", "Replay execute cùng 1 quote 5 lần", okc > 1, f"{okc}/5 giao dịch được tạo")

# A9 bẫy
app = new_app(); c = app.test_client()
c.get("/api/v1/rates", headers=FULL); c.get("/api/internal/rates-export", headers=FULL)
r = c.get("/api/health", headers=FULL); r2 = c.get("/api/auth/me", headers=FULL)
rec("A9", "Crawler chạm đường dẫn bẫy rồi vẫn tiếp tục truy cập bình thường", r2.status_code == 401, f"request kế tiếp HTTP {r2.status_code} {(r2.get_json() or {}).get('error','')}")

# A10 làm ngập log
app = new_app()
for _ in range(500): app.test_client().get("/api/public-data", headers={"User-Agent": "curl/8"})
n = len(list_logs(limit=100000))
rec("A10", "Làm ngập audit log bằng 500 request UA curl", n > 100, f"{n} dòng log bị tạo ra")

# A11 người dùng thật: hỏi 2 mức tiền khác hẳn liền nhau
app = new_app(); setup_preset(app)
c = app.test_client(); _, t, _ = login(c, "cust001")
a_ = post(c, "/api/transaction/quote", t, {"currency": "USD", "side": "SELL", "amount": 1000}).status_code
advance(5)
b_ = post(c, "/api/transaction/quote", t, {"currency": "USD", "side": "SELL", "amount": 50000}).status_code
rec("L1", "[NGƯỜI DÙNG THẬT] KH hỏi 1.000 rồi 50.000 USD cách nhau 5 giây", b_ == 200, f"HTTP {a_} rồi {b_} (success=True nghĩa là người thật được phục vụ)")

# S: bot thích nghi chạy 4 giờ giả lập
def adaptive_bot(hours=4, seed=7):
    rnd = random.Random(seed); app = new_app(); setup_preset(app)
    start = now(); end = start + hours * 3600
    c = app.test_client(); code, tok, _ = login(c, "cust001"); got = 0; relogins = 0; locked_at = None
    first_block = None; stats = {}
    while now() < end:
        advance(rnd.uniform(6, 14))
        r = post(c, "/api/transaction/quote", tok, {"currency": "USD", "side": "SELL", "amount": rnd.randint(1000, 90000)})
        j = r.get_json() or {}
        if r.status_code == 200: got += 1; continue
        err = j.get("error", str(r.status_code)); stats[err] = stats.get(err, 0) + 1
        if r.status_code == 428 and V2:
            ch = j["challenge"]; nonce = pow_mod.solve(ch["prefix"], ch["bits"])
            r = post(c, "/api/transaction/quote", tok, {"currency": "USD", "side": "SELL", "amount": rnd.randint(1000, 90000)},
                     {"X-Challenge-Id": ch["challenge_id"], "X-Challenge-Nonce": str(nonce)})
            if r.status_code == 200: got += 1
        elif r.status_code == 429 and j.get("retry_after_seconds"): advance(j["retry_after_seconds"])
        elif r.status_code == 429: advance(30)
        elif err == "BLOCKED" or err == "USER_BLOCKED":
            locked_at = (now() - start) / 60; break
        elif r.status_code in (401,):
            code, tok, jj = login(c, "cust001"); relogins += 1
            if code != 200: locked_at = (now() - start) / 60; break
    return got, relogins, locked_at, stats
got, rel, lock, stats = adaptive_bot()
rec("S1", "Bot THÍCH NGHI 4 giờ (nhịp ngẫu nhiên 6-14s, đổi số tiền, giải PoW, tôn trọng Retry-After, đăng nhập lại): số giá lấy được",
    got > 0, json.dumps({"prices": got, "relogins": rel, "locked_after_min": None if lock is None else round(lock, 1), "rejections": stats}))
rec("S1_n", "prices", got, "")
print(json.dumps({"version": "v2" if V2 else ("theirs" if "theirs" in ROOT else "orig"), "results": R}, ensure_ascii=False))
