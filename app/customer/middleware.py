"""
Anti-Bot middleware cho Pricing & Transaction API.

Các lớp bảo vệ (đã loại bỏ sign-helper – không còn cấp chữ ký cho client):
1. User-Agent bot detection
2. Session fingerprint (strict)
3. Authentication (user_id trong session)
4. CSRF token (header X-CSRF-Token khớp session cấp lúc login)
5. HMAC vẫn được chấp nhận nếu client tự ký (API tích hợp), nhưng không bắt buộc khi có CSRF hợp lệ
"""

import hmac
from functools import wraps

from flask import request, jsonify, session

from utils.security import (
    verify_fingerprint,
    verify_pricing_signature,
    is_suspicious_user_agent,
)


def pricing_security_required(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # 1. Chặn User-Agent bot
        if is_suspicious_user_agent():
            return jsonify({
                "error": "ACCESS_DENIED",
                "message": "Request bị từ chối",
            }), 403

        # 2. Fingerprint session (strict)
        if not verify_fingerprint(strict=True):
            return jsonify({
                "error": "INVALID_SESSION",
                "message": "Phiên làm việc không hợp lệ hoặc fingerprint lệch",
            }), 403

        # 3. Authentication
        user_id = session.get("user_id")
        if not user_id:
            return jsonify({
                "error": "AUTHENTICATION_REQUIRED",
                "message": "Yêu cầu đăng nhập",
            }), 401

        # 4. CSRF hoặc HMAC hợp lệ
        csrf = (request.headers.get("X-CSRF-Token") or "").strip()
        expected_csrf = (session.get("csrf_token") or "").strip()
        has_valid_csrf = bool(expected_csrf and csrf and hmac.compare_digest(csrf, expected_csrf))

        timestamp = request.headers.get("X-Timestamp")
        signature = request.headers.get("X-Signature")
        nonce = request.headers.get("X-Nonce", "")
        has_valid_hmac = False
        if timestamp and signature:
            body = request.get_data(as_text=True) or ""
            try:
                has_valid_hmac = verify_pricing_signature(
                    timestamp=timestamp,
                    signature=signature,
                    method=request.method,
                    path=request.path,
                    body=body,
                    nonce=nonce,
                    max_age_seconds=60,
                )
            except RuntimeError:       # API_SIGNING_SECRET chưa cấu hình -> không chấp nhận HMAC
                has_valid_hmac = False

        if not has_valid_csrf and not has_valid_hmac:
            return jsonify({
                "error": "CSRF_OR_SIGNATURE_REQUIRED",
                "message": "Thiếu X-CSRF-Token hợp lệ hoặc chữ ký HMAC",
            }), 401

        return func(*args, **kwargs)

    return wrapper


def auth_required(func):
    """Chỉ yêu cầu đăng nhập + fingerprint (không CSRF/HMAC)."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if is_suspicious_user_agent():
            return jsonify({
                "error": "ACCESS_DENIED",
                "message": "Request bị từ chối",
            }), 403
        if not verify_fingerprint(strict=True):
            return jsonify({
                "error": "INVALID_SESSION",
                "message": "Phiên làm việc không hợp lệ",
            }), 403
        if not session.get("user_id"):
            return jsonify({
                "error": "AUTHENTICATION_REQUIRED",
                "message": "Yêu cầu đăng nhập",
            }), 401
        return func(*args, **kwargs)
    return wrapper
