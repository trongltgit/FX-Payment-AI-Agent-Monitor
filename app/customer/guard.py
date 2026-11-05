"""
Anti-Bot Gate – cổng chặn TOÀN CỤC chạy trước mọi route.

v1 gắn kiểm tra rải rác bằng decorator trên từng route => route nào quên decorator
(ví dụ /api/hq/blocked/lock, /api/cn/assign-cif) thì không có CSRF/UA/fingerprint.
v2 đặt MỘT before_request: mặc định mọi thứ dưới /api đều bị kiểm tra, route chỉ được
miễn trừ khi nằm trong danh sách ngoại lệ rõ ràng ở đầu file.

Pipeline (dừng ở lần chặn đầu tiên):
  0. request-id
  1. IP đang bị ban
  2. Honeypot (bẫy cho crawler)
  3. User-Agent bot
  4. Hồ sơ header "giống trình duyệt thật"
  5. Phiên: user bị khóa / fingerprint lệch / nạp lại quyền từ nguồn chuẩn
  6. Ngân sách request theo user (chống cào GET danh mục)
  7. Phương thức ghi: Origin + Sec-Fetch-Site + CSRF token
"""
import hmac
import os
import uuid
from urllib.parse import urlparse

from flask import current_app, g, jsonify, render_template, request, session

from services import bot_defense
from services.audit_log import add_log
from utils import store
from utils.security import (
    get_client_ip,
    header_profile,
    is_suspicious_user_agent,
    verify_fingerprint,
)
from utils.server_session import revoke_user

UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}

PUBLIC_API = {"/api/health", "/api/pricing/health"}
CSRF_EXEMPT = {"/api/auth/login"}          # chưa có phiên nên chưa có token; login có form-token + PoW riêng
HMAC_BLUEPRINTS = {"transaction", "pricing"}  # có decorator tự kiểm CSRF *hoặc* HMAC cho client tích hợp

TRAP_EXACT = {"/api/internal/rates-export", "/api/v1/rates", "/api/v1/prices", "/api/export/all-prices"}
TRAP_PREFIX = ("/wp-", "/phpmyadmin", "/.git", "/.env", "/admin", "/api/internal/")

REQ_BUDGET = {"CUSTOMER": 60, "STAFF": 240}   # request/phút/tài khoản (mọi endpoint)


def _env_bool(name, default="1"):
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


def is_api() -> bool:
    return request.path.startswith("/api/")


def deny(code: str, message: str, status: int = 403, **extra):
    if is_api():
        body = {"error": code, "message": message}
        body.update(extra)
        resp = jsonify(body)
        resp.status_code = status
        return resp
    return render_template("blocked.html", reason=message), status


def log_throttled(event: str, ip: str, every: int = 30, **kw):
    """Chống bot làm ngập audit log: cùng (event, ip) chỉ ghi 1 dòng / `every` giây."""
    if store.setnx(f"logthr:{event}:{ip}", "1", ttl=every):
        add_log(event, ip=ip, **kw)


def is_trap(path: str) -> bool:
    return path in TRAP_EXACT or path.startswith(TRAP_PREFIX)


def _refresh_profile(uid: str) -> bool:
    """Nạp lại role / CIF được phép / chi nhánh từ nguồn chuẩn ở MỖI request.
    Đổi quyền (Admin CN gán lại CIF, TSC đổi role) có hiệu lực ngay, không đợi hết phiên."""
    from app.customer.mock_db import get_demo_user
    u = get_demo_user(uid)
    if not u:
        return False
    session["role"] = u.get("role")
    session["user_name"] = u.get("name")
    session["branch_id"] = u.get("branch_id")
    session["branch_ids"] = u.get("branch_ids") or []
    permitted = u.get("permitted_customers") or []
    session["permitted_customers"] = permitted
    cid = session.get("customer_id")
    if cid and u.get("role") != "CUSTOMER" and cid not in permitted:
        session.pop("customer_id", None)
        session.pop("cif", None)
    return True


def request_gate():
    g.request_id = uuid.uuid4().hex[:12]
    g.header_score = 0
    g.client_ip = ip = get_client_ip()

    if request.endpoint == "static":
        return None

    # 1. IP bị ban
    if bot_defense.is_ip_banned(ip):
        return deny("IP_BANNED", "Địa chỉ IP tạm thời bị chặn do hành vi bất thường.", 403)

    # 2. Honeypot – người dùng thật không bao giờ truy cập các đường dẫn này
    if is_trap(request.path):
        uid = session.get("user_id") or ""
        bot_defense.ban_ip(ip, reason=f"honeypot:{request.path}", ttl=86400)
        add_log("honeypot_hit", user_id=uid, ip=ip, level="critical",
                detail={"path": request.path, "ua": (request.headers.get("User-Agent") or "")[:120]})
        if uid:
            from app.customer.mock_db import block_user
            block_user(uid, "honeypot", blocked_by="system")
        resp = jsonify({"error": "NOT_FOUND"})
        resp.status_code = 404
        return resp

    if not is_api() or request.path in PUBLIC_API:
        return None

    # 3. User-Agent bot
    if is_suspicious_user_agent():
        bot_defense.ip_strike(ip, "bad_user_agent", weight=3)
        log_throttled("crawl_attempt", ip, level="warn", user_id=session.get("user_id") or "",
                      role=session.get("role") or "ANON",
                      detail={"path": request.path, "reason": "suspicious_ua",
                              "ua": (request.headers.get("User-Agent") or "")[:120]})
        return deny("CRAWL_BLOCKED", "Phát hiện User-Agent bot/crawler. Truy cập bị từ chối.", 403)

    # 4. Header profile
    score, reasons = header_profile()
    g.header_score = score
    if score >= 40 and _env_bool("STRICT_BROWSER_HEADERS"):
        bot_defense.ip_strike(ip, "header_profile", weight=3)
        log_throttled("header_mismatch", ip, level="warn", user_id=session.get("user_id") or "",
                      detail={"score": score, "reasons": reasons, "path": request.path})
        return deny("BROWSER_PROFILE_MISMATCH", "Yêu cầu không giống một trình duyệt hợp lệ.", 403)

    # 5. Phiên
    uid = session.get("user_id")
    if uid:
        from app.customer.mock_db import is_user_blocked
        if is_user_blocked(uid):
            session.clear()
            revoke_user(uid)
            return deny("USER_BLOCKED", "Tài khoản đã bị khóa.", 403)
        if not verify_fingerprint():
            add_log("fingerprint_mismatch", user_id=uid, ip=ip, level="warn",
                    detail={"path": request.path})
            session.clear()
            return deny("INVALID_SESSION", "Phiên làm việc không hợp lệ (fingerprint lệch).", 403)
        if not _refresh_profile(uid):
            session.clear()
            return deny("AUTHENTICATION_REQUIRED", "Tài khoản không còn tồn tại.", 401)

        # 6. Ngân sách request theo tài khoản
        role = (session.get("role") or "").upper()
        budget = REQ_BUDGET["CUSTOMER" if role == "CUSTOMER" else "STAFF"]
        store.events_add(f"req:{uid}", "", keep_seconds=120)
        if store.events_count(f"req:{uid}", 60) > budget:
            log_throttled("user_request_budget", ip, user_id=uid, level="warn",
                          detail={"budget": budget, "path": request.path})
            resp = jsonify({"error": "RATE_LIMITED", "message": "Quá nhiều yêu cầu. Vui lòng chậm lại."})
            resp.status_code = 429
            resp.headers["Retry-After"] = "30"
            return resp

    # 7. Request ghi dữ liệu
    if request.method in UNSAFE:
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return deny("CSRF_ORIGIN", "Origin không hợp lệ.", 403)
        sfs = request.headers.get("Sec-Fetch-Site")
        if sfs and sfs not in {"same-origin", "none"}:
            return deny("CSRF_ORIGIN", "Yêu cầu cross-site bị từ chối.", 403)

        if request.path in CSRF_EXEMPT:
            return None
        if not uid:
            return deny("AUTHENTICATION_REQUIRED", "Yêu cầu đăng nhập.", 401)
        if request.blueprint in HMAC_BLUEPRINTS:
            return None     # decorator pricing_security_required kiểm CSRF hoặc HMAC
        sent = (request.headers.get("X-CSRF-Token") or "").strip()
        expected = session.get("csrf_token") or ""
        if not (sent and expected and hmac.compare_digest(sent, expected)):
            add_log("csrf_rejected", user_id=uid, ip=ip, level="warn", detail={"path": request.path})
            return deny("CSRF_INVALID", "Thiếu hoặc sai X-CSRF-Token.", 403)
    return None


def security_headers(resp):
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("X-Frame-Options", "DENY")
    h.setdefault("Referrer-Policy", "same-origin")
    h.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    ts = ""
    if os.environ.get("TURNSTILE_SECRET_KEY"):
        ts = " https://challenges.cloudflare.com"
    # 'unsafe-inline' còn do các portal dùng onclick= nội tuyến (xem báo cáo: bước nâng cấp sang nonce)
    h.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; script-src 'self' 'unsafe-inline'" + ts +
        "; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
        "; frame-src" + (ts or " 'none'") + "; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
    )
    if current_app.config.get("SESSION_COOKIE_SECURE"):
        h.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if request.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
        h["Pragma"] = "no-cache"
    if getattr(g, "request_id", None):
        h["X-Request-ID"] = g.request_id
    return resp


def init_guard(app):
    app.before_request(request_gate)
    app.after_request(security_headers)

    @app.errorhandler(429)
    def too_many(e):
        ip = get_client_ip()
        if not session.get("user_id"):
            bot_defense.ip_strike(ip, "rate_limit_breach", weight=2)
        resp = jsonify({"error": "RATE_LIMITED", "message": "Quá nhiều yêu cầu. Vui lòng thử lại sau."})
        resp.status_code = 429
        resp.headers["Retry-After"] = "30"
        return resp

    @app.errorhandler(413)
    def too_large(e):
        return jsonify({"error": "PAYLOAD_TOO_LARGE", "message": "Dữ liệu gửi lên quá lớn."}), 413
