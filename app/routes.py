"""
Main routes + Auth + API công khai / bảo vệ
"""

import time
import secrets

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    session,
    redirect,
)

import os
import random

from utils.security import (
    get_client_fingerprint,
    verify_fingerprint,
    bind_fingerprint,
    is_suspicious_user_agent,
    get_client_ip,
)
from utils import pow as pow_mod
from utils import store
from utils import totp as totp_mod
from utils.server_session import revoke_user
from app import auth_guard
from app import config as cfg
from services import bot_defense
from services.audit_log import add_log
from utils.rate_limit import custom_rate_limit
from app.customer.service import CustomerService
from app.middleware import auth_required
from services.hq_policy import hq_policy_service, HQPolicyError
from services.market_rate import market_rate_service, MarketRateError
from functools import wraps

main_bp = Blueprint("main", __name__)
api_bp = Blueprint("api", __name__)

customer_service = CustomerService()


@main_bp.route("/")
@custom_rate_limit("30 per minute")
def index():
    """Trang đăng nhập chung – luôn hiện form login"""
    return render_template("index.html", form_token=auth_guard.issue_form_token())


@main_bp.route("/login/hq")
@custom_rate_limit("30 per minute")
def login_hq():
    return render_template(
        "login.html",
        form_token=auth_guard.issue_form_token(),
        portal_title="Hội sở",
        portal_desc="Quản lý chính sách giá cấp 1",
        expected_role="HQ",
        redirect_url="/portal/hq",
        default_user="hq01",
    )


@main_bp.route("/login/cn")
@custom_rate_limit("30 per minute")
def login_cn():
    return render_template(
        "login.html",
        form_token=auth_guard.issue_form_token(),
        portal_title="Chi nhánh",
        portal_desc="Báo giá và giao dịch khách hàng",
        expected_role="PNV,CN_ADMIN",
        redirect_url="/portal/cn",
        default_user="staff01",
    )


@main_bp.route("/login/kh")
@custom_rate_limit("30 per minute")
def login_kh():
    return render_template(
        "login.html",
        form_token=auth_guard.issue_form_token(),
        portal_title="Khách hàng",
        portal_desc="Xem giá và xác nhận giao dịch",
        expected_role="CUSTOMER",
        redirect_url="/portal/kh",
        default_user="cust001",
    )


def _session_ok() -> bool:
    """Phiên đã đăng nhập phải khớp fingerprint lúc đăng nhập (không re-bind)."""
    if not session.get("user_id"):
        return False
    if not verify_fingerprint(strict=True):
        session.clear()
        return False
    return True


def _require_role(role: str):
    if not _session_ok():
        return None, "login"
    if (session.get("role") or "").upper() != role.upper():
        return render_template("blocked.html", reason="Tài khoản không có quyền truy cập trang này"), 403
    return None, "ok"


@main_bp.route("/portal/hq")
@custom_rate_limit("30 per minute")
def portal_hq():
    err, st = _require_role("HQ")
    if st == "login":
        return redirect("/")
    if err:
        return err, st
    return render_template("portal_hq.html", user_name=session.get("user_name"))


@main_bp.route("/portal/cn")
@custom_rate_limit("30 per minute")
def portal_cn():
    if not _session_ok():
        return redirect("/")
    role = (session.get("role") or "").upper()
    if role not in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
        return render_template("blocked.html", reason="Tài khoản không có quyền truy cập trang này"), 403
    return render_template(
        "portal_cn.html",
        user_name=session.get("user_name"),
        role=role,
        is_admin=(role == "CN_ADMIN"),
    )


@main_bp.route("/portal/kh")
@custom_rate_limit("30 per minute")
def portal_kh():
    err, st = _require_role("CUSTOMER")
    if st == "login":
        return redirect("/")
    if err:
        return err, st
    return render_template("portal_kh.html", user_name=session.get("user_name"))


@main_bp.route("/dashboard")
@custom_rate_limit("20 per minute")
def dashboard():
    role = (session.get("role") or "").upper()
    if role == "HQ":
        return portal_hq()
    if role in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
        return portal_cn()
    if role == "CUSTOMER":
        return portal_kh()
    return index()


@main_bp.route("/robots.txt")
def robots():
    """Khai báo đường dẫn cấm cho crawler tử tế. Crawler lờ đi và truy cập mấy đường dẫn bẫy
    (/api/internal/, /api/v1/) sẽ bị ban IP ngay (xem app/guard.py)."""
    from flask import Response
    body = "User-agent: *\nDisallow: /api/\nDisallow: /portal/\nDisallow: /api/internal/\nDisallow: /api/v1/\n"
    return Response(body, mimetype="text/plain")


@main_bp.route("/blocked")
def blocked():
    return render_template("blocked.html", reason="Truy cập bị chặn"), 403


# ============================================================
# AUTH (Demo)
# ============================================================

@api_bp.route("/auth/challenge", methods=["GET"])
@custom_rate_limit("20 per minute")
def auth_challenge():
    """Phát challenge Proof-of-Work. Độ khó tăng nếu IP đang bị nghi dò mật khẩu."""
    ip = get_client_ip()
    bits = pow_mod.default_bits() + auth_guard.extra_pow_bits("", ip)
    return jsonify({"status": "success", "challenge": pow_mod.issue(bits=bits, bind=ip)}), 200


def _login_fail(code, message, status, username="", ip="", count=True, **extra):
    """Phản hồi thất bại: có trễ nhỏ + đếm lần sai để khóa tạm."""
    if count and username:
        auth_guard.register_failure(username, ip)
    delay = float(os.environ.get("LOGIN_FAIL_DELAY", "0.3"))
    if delay > 0:
        time.sleep(random.uniform(delay * 0.5, delay))
    body = {"error": code, "message": message, "form_token": auth_guard.issue_form_token()}
    body.update(extra)
    return jsonify(body), status


@api_bp.route("/auth/login", methods=["POST"])
@custom_rate_limit("10 per minute")
def login():
    """
    Đăng nhập. Body:
      { username, password, otp?, form_token, pow:{challenge_id,nonce}, website(honeypot, phải rỗng),
        turnstile?, hs?: {webdriver, dwell_ms, keys, moves} }
    Production: thay authenticate() bằng SSO/LDAP; MFA bắt buộc cho HQ & Admin CN.
    """
    ip = get_client_ip()
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()[:64]
    password = str(data.get("password", ""))[:256]

    # 1. IP/tài khoản đang bị khóa tạm vì đăng nhập sai nhiều
    remaining = auth_guard.login_locked(username, ip)
    if remaining:
        return _login_fail("TOO_MANY_ATTEMPTS",
                           f"Đăng nhập sai quá nhiều lần. Thử lại sau {remaining} giây.",
                           429, count=False, retry_after_seconds=remaining)

    # 2. Honeypot: ô ẩn mà người thật không thấy
    if str(data.get("website", "")).strip():
        bot_defense.ip_strike(ip, "honeypot_field", weight=10)
        add_log("login_bot", user_id=username, ip=ip, level="critical", detail={"why": "honeypot_field"})
        return _login_fail("ACCESS_DENIED", "Request bị từ chối", 403, count=False)

    # 3. Form-token ký + dùng 1 lần + thời gian tối thiểu
    ok, why = auth_guard.check_form_token(str(data.get("form_token", "")))
    if not ok:
        bot_defense.ip_strike(ip, f"login_{why}", weight=2)
        add_log("login_bot", user_id=username, ip=ip, level="warn", detail={"why": why})
        return _login_fail("FORM_TOKEN_INVALID",
                           "Phiên đăng nhập không hợp lệ. Tải lại trang và thử lại.", 400, count=False)

    # 4. Proof-of-Work
    pw = data.get("pow") or {}
    # Độ khó đã được "đóng dấu" vào challenge lúc phát (tăng theo IP đang bị nghi); ở đây chỉ cần >= mức nền
    ok, why = pow_mod.verify(str(pw.get("challenge_id", "")), pw.get("nonce"), bind=ip,
                             min_bits=pow_mod.default_bits())
    if not ok:
        add_log("login_bot", user_id=username, ip=ip, level="warn", detail={"why": f"pow_{why}"})
        return _login_fail("POW_REQUIRED", "Thiếu hoặc sai bằng chứng xử lý (PoW). Tải lại trang.",
                           400, count=False)

    # 5. Turnstile (nếu cấu hình)
    if auth_guard.turnstile_enabled() and not auth_guard.verify_turnstile(str(data.get("turnstile", "")), ip):
        add_log("login_bot", user_id=username, ip=ip, level="warn", detail={"why": "turnstile_failed"})
        return _login_fail("CAPTCHA_FAILED", "Xác minh CAPTCHA không thành công.", 400, count=False)

    # 6. Tín hiệu automation từ trình duyệt
    hs = data.get("hs") if isinstance(data.get("hs"), dict) else {}
    login_risk = 0
    if hs.get("webdriver") is True:
        bot_defense.ip_strike(ip, "webdriver", weight=5)
        add_log("login_bot", user_id=username, ip=ip, level="critical", detail={"why": "navigator.webdriver"})
        return _login_fail("AUTOMATION_DETECTED", "Phát hiện trình duyệt tự động hóa.", 403, count=False)
    if int(hs.get("keys", 0) or 0) + int(hs.get("moves", 0) or 0) == 0:
        login_risk += 15    # không có thao tác nào: chỉ cộng điểm (autofill/trình quản lý mật khẩu vẫn hợp lệ)

    if not username or not password:
        return _login_fail("INVALID_REQUEST", "Thiếu username hoặc password.", 400, count=False)

    # 7. Xác thực mật khẩu (băm, thời gian không đổi)
    user = customer_service.authenticate(username, password)
    if not user:
        add_log("login_failed", user_id=username, ip=ip, level="warn")
        return _login_fail("INVALID_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu.", 401, username, ip)

    from app.customer.mock_db import is_user_blocked
    if is_user_blocked(user["user_id"]):
        return _login_fail("USER_BLOCKED",
                           "Tài khoản đã bị khóa do hành vi bất thường / bot. Liên hệ TSC để mở khóa.",
                           403, count=False, redirect="/blocked")

    # 8. MFA (bắt buộc cho role cấu hình, mặc định HQ & CN_ADMIN ở production)
    if (user.get("role") or "").upper() in cfg.mfa_required_roles():
        secret = user.get("totp_secret")
        if not secret:
            add_log("mfa_not_configured", user_id=user["user_id"], ip=ip, level="critical")
            return _login_fail("MFA_NOT_CONFIGURED", "Tài khoản chưa đăng ký MFA. Liên hệ TSC.", 403, count=False)
        otp = str(data.get("otp", "")).strip()
        if not otp:
            return jsonify({"error": "MFA_REQUIRED", "message": "Nhập mã OTP 6 số.",
                            "form_token": auth_guard.issue_form_token()}), 401
        if not totp_mod.verify(user["user_id"], secret, otp):
            add_log("mfa_failed", user_id=user["user_id"], ip=ip, level="warn")
            return _login_fail("INVALID_OTP", "Mã OTP không đúng hoặc đã dùng.", 401, username, ip)

    # ---- Thành công: phiên mới (chống session fixation), 1 phiên/user với KH
    auth_guard.clear_failures(username, ip)
    session.clear()
    session.rotate()
    single = {r.strip().upper() for r in os.environ.get("SINGLE_SESSION_ROLES", "CUSTOMER").split(",")}
    if (user.get("role") or "").upper() in single:
        revoke_user(user["user_id"])

    bind_fingerprint()
    session["user_id"] = user["user_id"]
    session["user_name"] = user.get("name")
    session["role"] = user.get("role")
    session["permitted_customers"] = user.get("permitted_customers") or []
    session["branch_id"] = user.get("branch_id")
    session["branch_ids"] = user.get("branch_ids") or []
    session["login_risk"] = login_risk
    session["login_at"] = int(time.time())
    session["login_ip"] = ip
    csrf_token = secrets.token_urlsafe(32)
    session["csrf_token"] = csrf_token

    if user.get("role") == "CUSTOMER" and user.get("customer_id"):
        session["customer_id"] = user["customer_id"]
        try:
            c = customer_service.get_customer(user["customer_id"])
            session["cif"] = c.get("cif")
        except Exception:
            session["cif"] = None

    bot_defense.record_login(user["user_id"], user.get("role"), ip)
    add_log("login_success", user_id=user["user_id"], role=user.get("role") or "", ip=ip,
            branch_id=user.get("branch_id") or "")

    return jsonify({
        "status": "success",
        "user": {
            "user_id": user["user_id"],
            "name": user.get("name"),
            "role": user.get("role"),
            "permitted_customers": user.get("permitted_customers") or [],
        },
        "csrf_token": csrf_token,
    }), 200


@api_bp.route("/auth/logout", methods=["POST"])
@custom_rate_limit("20 per minute")
def logout():
    uid = session.get("user_id")
    session.clear()           # xóa bản ghi phiên phía server -> cookie này vô dụng
    if uid:
        add_log("logout", user_id=uid, ip=get_client_ip())
    return jsonify({"status": "success", "message": "Đã đăng xuất"}), 200


@api_bp.route("/auth/me", methods=["GET"])
@custom_rate_limit("30 per minute")
def me():
    if not session.get("user_id"):
        return jsonify({"error": "NOT_AUTHENTICATED"}), 401
    return jsonify({
        "status": "success",
        "user": {
            "user_id": session.get("user_id"),
            "name": session.get("user_name"),
            "role": session.get("role"),
            "customer_id": session.get("customer_id"),
            "cif": session.get("cif"),
            "permitted_customers": session.get("permitted_customers") or [],
        },
        "csrf_token": session.get("csrf_token"),
    }), 200


@api_bp.route("/auth/select-customer", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
def select_customer():
    """
    Staff chọn CIF được phép.
    Body: { "customer_id": "CUST001" }
    """
    data = request.get_json(silent=True) or {}
    customer_id = str(data.get("customer_id", "")).strip()
    if not customer_id:
        return jsonify({"error": "INVALID_REQUEST", "message": "Thiếu customer_id"}), 400

    user = {
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "customer_id": session.get("customer_id"),
        "permitted_customers": session.get("permitted_customers") or [],
    }
    if not customer_service.check_user_access(user, customer_id):
        return jsonify({
            "error": "ACCESS_DENIED",
            "message": "Bạn không có quyền với CIF này.",
        }), 403

    try:
        customer = customer_service.get_customer(customer_id)
    except Exception as e:
        return jsonify({"error": "CUSTOMER_ERROR", "message": str(e)}), 400

    session["customer_id"] = customer["customer_id"]
    session["cif"] = customer.get("cif")

    return jsonify({
        "status": "success",
        "customer": {
            "customer_id": customer["customer_id"],
            "cif": customer.get("cif"),
            "customer_name": customer.get("customer_name"),
            "segment": customer.get("segment"),
            "pricing_tier": customer.get("pricing_tier"),
        },
    }), 200




@api_bp.route("/branches", methods=["GET"])
@custom_rate_limit("30 per minute")
@auth_required
def list_branches():
    user = {
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "branch_id": session.get("branch_id"),
        "permitted_customers": session.get("permitted_customers") or [],
    }
    items = customer_service.list_branches(user)
    # Không lộ customer_ids thừa cho CN nếu cần – HQ được xem
    safe = []
    for b in items:
        if not b:
            continue
        safe.append({
            "branch_id": b["branch_id"],
            "branch_name": b["branch_name"],
        })
    return jsonify({"status": "success", "branches": safe}), 200


@api_bp.route("/branches/<branch_id>/customers", methods=["GET"])
@custom_rate_limit("30 per minute")
@auth_required
def branch_customers(branch_id):
    user = {
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "branch_id": session.get("branch_id"),
        "permitted_customers": session.get("permitted_customers") or [],
    }
    items = customer_service.list_customers_by_branch(user, branch_id)
    return jsonify({"status": "success", "customers": items}), 200




@api_bp.route("/cn/margin-preset", methods=["POST"])
@custom_rate_limit("30 per minute")
@auth_required
def cn_set_margin_preset():
    """CN cài margin sẵn cho CIF (KH online dùng)."""
    role = (session.get("role") or "").upper()
    if role not in {"PNV", "STAFF", "BRANCH", "CN_ADMIN", "HQ"}:
        return jsonify({"error": "FORBIDDEN", "message": "Chỉ chi nhánh được cài margin."}), 403
    data = request.get_json(silent=True) or {}
    customer_id = str(data.get("customer_id", "")).strip()
    currency = str(data.get("currency", "")).upper().strip()
    side = str(data.get("side", "")).upper().strip()
    margin = data.get("margin", 0)
    nsdh_points = data.get("nsdh_points", 0)
    use_nsdh = bool(data.get("use_nsdh", False))
    if not customer_id or not currency or not side:
        return jsonify({"error": "INVALID", "message": "Thiếu customer_id, currency hoặc side."}), 400
    user = {
        "user_id": session.get("user_id"),
        "role": role,
        "permitted_customers": session.get("permitted_customers") or [],
        "customer_id": session.get("customer_id"),
    }
    if not customer_service.check_user_access(user, customer_id):
        return jsonify({"error": "ACCESS_DENIED", "message": "Không có quyền CIF này."}), 403
    # Margin CN không được vượt trần TSC
    try:
        from services.hq_policy import hq_policy_service
        cust = customer_service.get_customer(customer_id)
        tier = str(cust.get("pricing_tier") or "BRONZE").upper()
        hq_policy_service.validate_branch_margin(tier, currency, margin)
    except Exception as e:
        return jsonify({
            "error": "MARGIN_EXCEEDED",
            "message": str(e) if str(e) else "Margin vượt trần Hội sở quy định cho chi nhánh.",
        }), 400
    from services.cn_margin_store import set_preset
    from services.audit_log import bump_cif_quote_version, add_log
    preset = set_preset(
        customer_id, currency, side, margin,
        nsdh_points=nsdh_points,
        use_nsdh=use_nsdh,
        amount_min=data.get("amount_min", 0),
        amount_max=data.get("amount_max"),
    )
    # Interrupt: làm hết hiệu lực quote cũ của CIF này
    ver = bump_cif_quote_version(customer_id)
    add_log(
        "cn_preset_changed",
        user_id=session.get("user_id") or "",
        role=role,
        customer_id=customer_id,
        branch_id=session.get("branch_id") or "",
        detail={"version": ver, "margin": margin, "use_nsdh": use_nsdh, "nsdh_points": nsdh_points},
    )
    return jsonify({"status": "success", "preset": preset, "cif_quote_version": ver}), 200


@api_bp.route("/cn/margin-preset", methods=["GET"])
@custom_rate_limit("30 per minute")
@auth_required
def cn_list_margin_preset():
    role = (session.get("role") or "").upper()
    if role not in {"PNV", "STAFF", "BRANCH", "CN_ADMIN", "HQ"}:
        return jsonify({"error": "FORBIDDEN"}), 403
    from services.cn_margin_store import list_presets_for_customers
    permitted = session.get("permitted_customers") or []
    items = list_presets_for_customers(permitted)
    return jsonify({"status": "success", "presets": items}), 200



@api_bp.route("/cn/margin-preset/delete", methods=["POST"])
@custom_rate_limit("30 per minute")
@auth_required
def cn_delete_margin_preset():
    role = (session.get("role") or "").upper()
    if role not in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
        return jsonify({"error": "FORBIDDEN", "message": "Chỉ chi nhánh được xóa margin."}), 403
    data = request.get_json(silent=True) or {}
    from services.cn_margin_store import delete_preset
    ok = delete_preset(
        str(data.get("customer_id", "")).strip(),
        str(data.get("currency", "")).upper().strip(),
        str(data.get("side", "")).upper().strip(),
    )
    if not ok:
        return jsonify({"error": "NOT_FOUND", "message": "Không tìm thấy margin đã lưu."}), 404
    return jsonify({"status": "success"}), 200


@api_bp.route("/customers/permitted", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
def permitted_customers():
    user = {
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "permitted_customers": session.get("permitted_customers") or [],
    }
    items = customer_service.list_permitted_customers(user)
    return jsonify({"status": "success", "customers": items}), 200




# ============================================================
# HQ POLICY API (chỉ role HQ)
# ============================================================

def hq_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "AUTHENTICATION_REQUIRED", "message": "Yêu cầu đăng nhập"}), 401
        if (session.get("role") or "").upper() != "HQ":
            return jsonify({
                "error": "HQ_ONLY",
                "message": "Chỉ Hội sở được truy cập chính sách giá cấp 1.",
            }), 403
        return func(*args, **kwargs)
    return wrapper


@api_bp.route("/hq/policy", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_get_policy():
    """Xem toàn bộ chính sách HQ – chỉ HQ."""
    data = hq_policy_service.get_all_policies()
    return jsonify({"status": "success", "policy": data}), 200


@api_bp.route("/hq/policy/base-spread", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_update_base_spread():
    """
    Cập nhật base_spread.
    Body: { "tier": "GOLD", "currency": "USD", "side": "SELL", "value": "14" }
    """
    data = request.get_json(silent=True) or {}
    try:
        hq_policy_service.update_base_spread(
            tier=data.get("tier", ""),
            currency=data.get("currency", ""),
            side=data.get("side", ""),
            value=data.get("value"),
        )
    except HQPolicyError as e:
        return jsonify({"error": "POLICY_ERROR", "message": str(e)}), 400
    return jsonify({
        "status": "success",
        "message": "Đã cập nhật base_spread.",
        "policy": hq_policy_service.get_all_policies(),
    }), 200


@api_bp.route("/hq/policy/max-branch-margin", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_update_max_margin():
    """
    Cập nhật trần margin chi nhánh.
    Body: { "tier": "GOLD", "currency": "USD", "value": "25" }
    """
    data = request.get_json(silent=True) or {}
    try:
        hq_policy_service.update_max_branch_margin(
            tier=data.get("tier", ""),
            currency=data.get("currency", ""),
            value=data.get("value"),
        )
    except HQPolicyError as e:
        return jsonify({"error": "POLICY_ERROR", "message": str(e)}), 400
    return jsonify({
        "status": "success",
        "message": "Đã cập nhật max_branch_margin.",
        "policy": hq_policy_service.get_all_policies(),
    }), 200


@api_bp.route("/hq/policy/tgdh-points", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_update_tgdh_points():
    """
    Cập nhật điểm điều hòa TGDH (NSDH).
    Body: { "currency": "USD", "value": "5" }  (dương = cộng, âm = trừ vào final)
    """
    data = request.get_json(silent=True) or {}
    try:
        hq_policy_service.update_tgdh_points(
            currency=data.get("currency", ""),
            value=data.get("value"),
        )
    except HQPolicyError as e:
        return jsonify({"error": "POLICY_ERROR", "message": str(e)}), 400
    return jsonify({
        "status": "success",
        "message": "Đã cập nhật tgdh_points (TGDH/NSDH).",
        "policy": hq_policy_service.get_all_policies(),
    }), 200


@api_bp.route("/hq/market-rate", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_get_market_rate():
    """Xem base TSC hiện tại + mode auto/manual."""
    return jsonify({
        "status": "success",
        "market": market_rate_service.get_all_rates(),
    }), 200


@api_bp.route("/hq/market-rate/mode", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_set_market_mode():
    """
    TSC set mode base price: auto (20s) hoặc manual.
    Body: { "mode": "auto" | "manual" }
    """
    data = request.get_json(silent=True) or {}
    try:
        mode = market_rate_service.set_mode(data.get("mode", ""))
    except MarketRateError as e:
        return jsonify({"error": "MARKET_ERROR", "message": str(e)}), 400
    return jsonify({
        "status": "success",
        "message": f"Đã chuyển mode base TSC sang '{mode}'.",
        "market": market_rate_service.get_all_rates(),
    }), 200


@api_bp.route("/hq/market-rate/set", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_set_manual_rate():
    """
    TSC set tay base price (tự chuyển sang manual nếu đang auto).
    Body: { "currency": "USD", "rate": "26250" }
    """
    data = request.get_json(silent=True) or {}
    try:
        rate = market_rate_service.set_manual_rate(
            currency=data.get("currency", ""),
            rate=data.get("rate"),
        )
    except MarketRateError as e:
        return jsonify({"error": "MARKET_ERROR", "message": str(e)}), 400
    return jsonify({
        "status": "success",
        "message": f"Đã set base {data.get('currency', '').upper()} = {rate} (mode manual).",
        "market": market_rate_service.get_all_rates(),
    }), 200



@api_bp.route("/cn/assign-cif", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
def cn_assign_cif():
    """Admin CN gán CIF cho nhân viên."""
    role = (session.get("role") or "").upper()
    if role != "CN_ADMIN":
        return jsonify({"error": "FORBIDDEN", "message": "Chỉ Admin CN được gán CIF."}), 403
    data = request.get_json(silent=True) or {}
    staff_id = str(data.get("staff_user_id", "")).strip()
    cids = data.get("customer_ids") or []
    from app.customer.mock_db import assign_cif_to_staff
    ok, msg = assign_cif_to_staff(session.get("user_id"), staff_id, cids)
    if not ok:
        return jsonify({"error": "ASSIGN_ERROR", "message": msg}), 400
    return jsonify({"status": "success", "message": msg}), 200


@api_bp.route("/cn/set-online", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
def cn_set_online():
    """CN bật/tắt online cho CIF (KH online mới login + hỏi giá được)."""
    role = (session.get("role") or "").upper()
    if role not in {"CN_ADMIN", "PNV", "STAFF", "HQ"}:
        return jsonify({"error": "FORBIDDEN", "message": "Không có quyền."}), 403
    data = request.get_json(silent=True) or {}
    cid = str(data.get("customer_id", "")).strip()
    online = bool(data.get("online", True))
    from app.customer.mock_db import set_customer_online
    ok, msg = set_customer_online(
        cid, online, role, branch_id=session.get("branch_id") or ""
    )
    if not ok:
        return jsonify({"error": "ONLINE_ERROR", "message": msg}), 400
    return jsonify({"status": "success", "message": msg, "customer_id": cid, "online": online}), 200


@api_bp.route("/cn/staff-list", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
def cn_staff_list():
    role = (session.get("role") or "").upper()
    if role != "CN_ADMIN":
        return jsonify({"error": "FORBIDDEN", "message": "Chỉ Admin CN."}), 403
    from app.customer.mock_db import DEMO_USERS
    branch_id = session.get("branch_id") or ""
    staff = [
        {
            "user_id": u["user_id"],
            "name": u.get("name"),
            "role": u.get("role"),
            "permitted_customers": u.get("permitted_customers") or [],
        }
        for u in DEMO_USERS.values()
        if u.get("branch_id") == branch_id and u.get("role") in {"PNV", "STAFF"}
    ]
    return jsonify({"status": "success", "staff": staff}), 200



@api_bp.route("/audit-logs/export", methods=["GET"])
@custom_rate_limit("10 per minute")
@auth_required
def export_audit_logs():
    """Xuất log CSV (Excel mở được). ?format=csv|pdf"""
    role = (session.get("role") or "").upper()
    if role not in {"HQ", "CN_ADMIN"}:
        return jsonify({"error": "FORBIDDEN"}), 403
    from services.audit_log import list_logs, logs_to_csv
    fmt = (request.args.get("format") or "csv").lower()
    logs = list_logs(
        role_viewer=role,
        branch_id=session.get("branch_id") or "",
        user_id=session.get("user_id") or "",
        limit=2000,
    )
    if fmt == "pdf":
        # PDF đơn giản dạng text
        from flask import Response
        lines = ["AUDIT LOG", "=" * 40]
        for x in logs:
            lines.append(
                f"{x.get('ts')} | {x.get('event')} | {x.get('user_id')} | "
                f"{x.get('customer_id')} | {x.get('ip')} | {x.get('detail')}"
            )
        body = "\n".join(lines)
        return Response(
            body,
            mimetype="application/pdf" if False else "text/plain",
            headers={"Content-Disposition": "attachment; filename=audit_log.txt"},
        )
    from flask import Response
    csv_data = logs_to_csv(logs)
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


@api_bp.route("/hq/users", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_list_users():
    from app.customer.mock_db import list_demo_users
    return jsonify({"status": "success", "users": list_demo_users()}), 200


@api_bp.route("/hq/users", methods=["POST"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_upsert_user():
    data = request.get_json(silent=True) or {}
    from app.customer.mock_db import tsc_upsert_user
    ok, msg = tsc_upsert_user("HQ", data)
    if not ok:
        return jsonify({"error": "USER_ERROR", "message": msg}), 400
    return jsonify({"status": "success", "message": msg}), 200


@api_bp.route("/hq/blocked", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_list_blocked():
    from app.customer.mock_db import list_blocked_users
    return jsonify({"status": "success", "blocked": list_blocked_users()}), 200


@api_bp.route("/hq/blocked/unlock", methods=["POST"])
@custom_rate_limit("10 per minute")
@auth_required
@hq_required
def hq_unlock_user():
    data = request.get_json(silent=True) or {}
    uid = str(data.get("user_id") or "").strip()
    from app.customer.mock_db import unlock_user
    from services.audit_log import add_log
    ok = unlock_user(uid)
    if not ok:
        return jsonify({"error": "NOT_FOUND", "message": "User không bị khóa hoặc không tồn tại."}), 404
    add_log("user_unlocked", user_id=session.get("user_id") or "", role="HQ",
            detail={"unlocked": uid}, level="info")
    return jsonify({"status": "success", "message": f"Đã mở khóa {uid}"}), 200


@api_bp.route("/hq/blocked/lock", methods=["POST"])
@custom_rate_limit("10 per minute")
@auth_required
@hq_required
def hq_lock_user():
    """TSC khóa tay user (test bot)."""
    data = request.get_json(silent=True) or {}
    uid = str(data.get("user_id") or "").strip()
    reason = str(data.get("reason") or "manual_lock")
    from app.customer.mock_db import block_user
    from services.audit_log import add_log
    info = block_user(uid, reason, blocked_by=session.get("user_id") or "hq")
    add_log("user_blocked", user_id=session.get("user_id") or "", role="HQ",
            detail=info, level="warn")
    return jsonify({"status": "success", "blocked": info}), 200


@api_bp.route("/hq/security-summary", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
@hq_required
def hq_security_summary():
    """Bảng điều khiển an ninh 60 phút gần nhất cho TSC: sự kiện, tài khoản/IP đáng ngờ, danh sách khóa."""
    from collections import Counter
    from services.audit_log import list_logs
    from app.customer.mock_db import list_blocked_users
    now = int(time.time())
    interesting = {"bot_blocked", "crawl_attempt", "force_relogin", "login_failed", "login_bot",
                   "login_locked", "honeypot_hit", "csrf_rejected", "fingerprint_mismatch",
                   "header_mismatch", "user_request_budget", "quote_throttled", "quote_challenge"}
    logs = [x for x in list_logs(role_viewer="HQ", limit=8000) if x["ts"] >= now - 3600]
    by_event = Counter(x["event"] for x in logs)
    by_user = Counter(x["user_id"] for x in logs if x["event"] in interesting and x["user_id"])
    by_ip = Counter(x["ip"] for x in logs if x["event"] in interesting and x["ip"])
    return jsonify({
        "status": "success",
        "window_minutes": 60,
        "store_backend": store.backend(),
        "events": dict(by_event),
        "top_suspicious_users": by_user.most_common(10),
        "top_suspicious_ips": by_ip.most_common(10),
        "blocked_users": list_blocked_users(),
        "banned_ips": bot_defense.list_banned_ips(),
    }), 200


@api_bp.route("/hq/banned-ips/unban", methods=["POST"])
@custom_rate_limit("10 per minute")
@auth_required
@hq_required
def hq_unban_ip():
    data = request.get_json(silent=True) or {}
    ip = str(data.get("ip") or "").strip()
    if not bot_defense.unban_ip(ip):
        return jsonify({"error": "NOT_FOUND", "message": "IP không bị chặn."}), 404
    add_log("ip_unbanned", user_id=session.get("user_id") or "", role="HQ", detail={"ip": ip})
    return jsonify({"status": "success", "message": f"Đã gỡ chặn {ip}"}), 200


# ============================================================
# Public / protected demo APIs
# ============================================================

@api_bp.route("/public-data")
@custom_rate_limit("20 per minute")
def public_data():
    from services.audit_log import add_log
    from utils.security import get_client_ip
    ua_bad = is_suspicious_user_agent()
    logged_in = bool(session.get("user_id"))
    if ua_bad or not logged_in:
        add_log(
            "crawl_attempt",
            user_id=session.get("user_id") or "",
            role=session.get("role") or "ANON",
            ip=get_client_ip(),
            level="warn",
            detail={
                "path": "/api/public-data",
                "logged_in": logged_in,
                "suspicious_ua": ua_bad,
                "ua": (request.headers.get("User-Agent") or "")[:120],
            },
        )
    if ua_bad:
        return jsonify({
            "error": "CRAWL_BLOCKED",
            "message": "Phát hiện User-Agent bot/crawler. Truy cập bị từ chối.",
            "warning": "CRAWLING_WITHOUT_LOGIN" if not logged_in else "SUSPICIOUS_UA",
        }), 403
    if not logged_in:
        return jsonify({
            "error": "LOGIN_REQUIRED",
            "message": "Cảnh báo: truy cập dữ liệu mà không đăng nhập (có thể là crawling).",
            "warning": "CRAWLING_WITHOUT_LOGIN",
        }), 401
    return jsonify({
        "status": "ok",
        "message": "Dữ liệu công khai",
        "timestamp": int(time.time()),
        "server": "anti-bot-pro",
    })


@api_bp.route("/user-data")
@custom_rate_limit("8 per minute")
def user_data():
    if not verify_fingerprint():
        return jsonify({"error": "Phiên làm việc không hợp lệ hoặc nghi bot"}), 403
    if not session.get("user_id"):
        return jsonify({"error": "AUTHENTICATION_REQUIRED"}), 401
    return jsonify({
        "status": "success",
        "user": {
            "id": session.get("user_id"),
            "name": session.get("user_name"),
            "role": session.get("role"),
            "note": "Dữ liệu đã được bảo vệ bởi nhiều lớp",
        },
        "timestamp": int(time.time()),
    })


@api_bp.route("/sensitive")
@custom_rate_limit("3 per minute")
def sensitive():
    if not verify_fingerprint():
        return jsonify({"error": "Access denied"}), 403
    if not session.get("user_id"):
        return jsonify({"error": "AUTHENTICATION_REQUIRED"}), 401
    return jsonify({
        "warning": "Endpoint nhạy cảm",
        "message": "Production phải có JWT + MFA + phân quyền chi tiết",
    })


@api_bp.route("/health")
def health():
    return jsonify({"status": "healthy", "service": "anti-bot-pro"})


@api_bp.route("/sign-helper", methods=["POST", "GET"])
def sign_helper_removed():
    """
    Đã loại bỏ. Không còn cấp chữ ký HMAC cho client.
    Client trình duyệt dùng session + X-CSRF-Token.
    Client tích hợp (API) tự ký bằng API_SIGNING_SECRET phía server của họ.
    """
    return jsonify({
        "error": "ENDPOINT_REMOVED",
        "message": "sign-helper đã bị vô hiệu hóa vì làm suy yếu chống bot. "
                   "Dùng X-CSRF-Token (lấy từ /api/auth/login hoặc /api/auth/me) "
                   "hoặc tự ký HMAC nếu là client tích hợp.",
    }), 410
