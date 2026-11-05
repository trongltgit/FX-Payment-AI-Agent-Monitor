"""
Bảo vệ đăng nhập (login là cửa chính của bot: dò mật khẩu, farm tài khoản, lấy phiên).

Thứ tự kiểm tra (rẻ -> đắt, mỗi bước bot đều phải trả giá):
  1. IP đang bị khóa tạm do đăng nhập sai nhiều
  2. Honeypot field (người không thấy, bot điền)
  3. Form-token ký + dùng 1 lần + phải "nhìn form" tối thiểu N giây
  4. Proof-of-Work (độ khó tăng nếu IP/tài khoản đang bị nghi)
  5. Cloudflare Turnstile (nếu cấu hình TURNSTILE_SECRET_KEY)
  6. Tín hiệu automation từ trình duyệt (navigator.webdriver...)
"""
import os
import secrets
import time
from typing import Optional, Tuple

from flask import current_app
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from services.audit_log import add_log
from services.bot_defense import ip_strike
from utils import pow as pow_mod
from utils import store

FAIL_WINDOW = 900   # 15 phút


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# ------------------------------------------------------------------ form token
def _ser():
    return URLSafeTimedSerializer(current_app.secret_key, salt="login-form")


def issue_form_token() -> str:
    return _ser().dumps({"n": secrets.token_hex(8), "t": int(time.time())})


def check_form_token(token: str) -> Tuple[bool, str]:
    if not token:
        return False, "missing_form_token"
    try:
        data = _ser().loads(token, max_age=1800)
    except SignatureExpired:
        return False, "form_token_expired"
    except BadSignature:
        return False, "form_token_invalid"
    min_secs = float(os.environ.get("LOGIN_MIN_FORM_SECONDS", "1.5"))
    if time.time() - data["t"] < min_secs:
        return False, "submitted_too_fast"
    if not store.setnx(f"ftok:{data['n']}", "1", ttl=1800):
        return False, "form_token_reused"
    return True, "ok"


# ------------------------------------------------------------------ Turnstile
def turnstile_enabled() -> bool:
    return bool(os.environ.get("TURNSTILE_SECRET_KEY", "").strip())


def verify_turnstile(token: str, ip: str) -> bool:
    secret = os.environ.get("TURNSTILE_SECRET_KEY", "").strip()
    if not secret:
        return True
    if not token:
        return False
    try:
        import requests
        r = requests.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": secret, "response": token, "remoteip": ip},
            timeout=4,
        )
        return bool(r.json().get("success"))
    except Exception:
        # Fail-closed: không xác minh được thì không cho đăng nhập
        return False


# ------------------------------------------------------------- đếm đăng nhập sai
def _k_ui(user, ip): return f"lf:ui:{user.lower()}|{ip}"
def _k_u(user): return f"lf:u:{user.lower()}"
def _k_ip(ip): return f"lf:ip:{ip}"


def login_locked(username: str, ip: str) -> int:
    """Số giây còn bị khóa (0 = không khóa)."""
    for k in (f"lock:ui:{username.lower()}|{ip}", f"lock:ip:{ip}"):
        t = store.ttl(k)
        if t > 0:
            return t
    return 0


def extra_pow_bits(username: str, ip: str) -> int:
    """Tài khoản/IP đang bị dò mật khẩu -> PoW khó hơn (+4 bit = x16 công)."""
    bonus = 0
    if store.get_int(_k_u(username)) >= 5 or store.get_int(_k_ip(ip)) >= 5:
        bonus += 4
    if store.exists(f"risk:chal:{username}"):
        bonus += 2
    return bonus


def register_failure(username: str, ip: str) -> None:
    lim_ui = _int_env("LOGIN_MAX_FAILS_USER_IP", 5)
    lim_ip = _int_env("LOGIN_MAX_FAILS_IP", 20)
    lock_secs = _int_env("LOGIN_LOCK_SECONDS", 900)
    n_ui = store.incr(_k_ui(username, ip), FAIL_WINDOW)
    store.incr(_k_u(username), FAIL_WINDOW)
    n_ip = store.incr(_k_ip(ip), FAIL_WINDOW)
    if n_ui >= lim_ui:
        store.set(f"lock:ui:{username.lower()}|{ip}", "1", ttl=lock_secs)
        add_log("login_locked", user_id=username, ip=ip, level="warn",
                detail={"scope": "user+ip", "fails": n_ui})
    if n_ip >= lim_ip:
        store.set(f"lock:ip:{ip}", "1", ttl=lock_secs)
        ip_strike(ip, "credential_stuffing", weight=5)
        add_log("login_locked", user_id=username, ip=ip, level="critical",
                detail={"scope": "ip", "fails": n_ip})


def clear_failures(username: str, ip: str) -> None:
    store.delete(_k_ui(username, ip))
    store.delete(f"lock:ui:{username.lower()}|{ip}")
