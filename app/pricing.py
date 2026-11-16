"""
Pricing API – response theo role
"""

import time

from flask import Blueprint, jsonify, request, session

from app.middleware import pricing_security_required
from app.customer.service import (
    CustomerService,
    CustomerNotFound,
    CustomerInactive,
)
from app.customer.repository import (
    CustomerAPIError,
    CustomerAPIUnavailable,
    CustomerAPITimeout,
)
from services.market_rate import market_rate_service, MarketRateError
from services.pricing_engine import pricing_engine, PricingError
from utils.rate_limit import custom_rate_limit, user_rate_limit
from services import bot_defense
from utils.security import get_client_ip
from flask import g

pricing_bp = Blueprint("pricing", __name__, url_prefix="/api/pricing")

customer_service = CustomerService()


@pricing_bp.route("/quote", methods=["POST"])
@custom_rate_limit("10 per minute")
@user_rate_limit("10 per minute")
@pricing_security_required
def quote():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "AUTHENTICATION_REQUIRED", "message": "Yêu cầu đăng nhập."}), 401

    data = request.get_json(silent=True) or {}
    currency = str(data.get("currency", "")).upper().strip()
    side = str(data.get("side", "")).upper().strip()
    amount = data.get("amount")
    branch_margin = data.get("branch_margin", 0)

    if not currency:
        return jsonify({"error": "INVALID_CURRENCY", "message": "Thiếu currency."}), 400
    if not side:
        return jsonify({"error": "INVALID_SIDE", "message": "Thiếu side."}), 400
    if amount is None:
        return jsonify({"error": "INVALID_AMOUNT", "message": "Thiếu amount."}), 400

    try:
        amount_value = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "INVALID_AMOUNT", "message": "Amount không hợp lệ."}), 400
    if amount_value <= 0:
        return jsonify({"error": "INVALID_AMOUNT", "message": "Amount phải lớn hơn 0."}), 400

    customer_id = session.get("customer_id")
    if not customer_id:
        return jsonify({"error": "CUSTOMER_CONTEXT_REQUIRED", "message": "Chưa gắn khách hàng."}), 403

    # Cùng bộ chấm điểm hành vi với /api/transaction/quote (quota giờ/ngày, metronome, enumeration...)
    ip = get_client_ip()
    role_ = (session.get("role") or "CUSTOMER").upper()
    d = bot_defense.assess(user_id, role_, ip, header_score=getattr(g, "header_score", 0),
                           login_risk=int(session.get("login_risk", 0) or 0), pending=1)
    if d.action in {"throttle", "block"}:
        return jsonify({"error": "QUOTE_THROTTLED", "message": "Bạn đã hỏi giá quá nhiều. Vui lòng thử lại sau.",
                        "retry_after_seconds": d.retry_after or 120}), 429
    bot_defense.record_quote(user_id, role_, ip, currency, side, amount_value)

    user = {
        "user_id": user_id,
        "role": session.get("role"),
        "customer_id": session.get("customer_id"),
        "permitted_customers": session.get("permitted_customers") or [],
    }
    if not customer_service.check_user_access(user, customer_id):
        return jsonify({"error": "ACCESS_DENIED", "message": "Không có quyền xem giá CIF này."}), 403

    role = (session.get("role") or "CUSTOMER").upper()
    if role == "CUSTOMER":
        branch_margin = 0

    try:
        customer = customer_service.get_customer(customer_id)
    except CustomerNotFound:
        return jsonify({"error": "CUSTOMER_NOT_FOUND", "message": "Không tìm thấy khách hàng."}), 404
    except CustomerInactive:
        return jsonify({"error": "CUSTOMER_INACTIVE", "message": "Khách hàng không hoạt động."}), 403
    except (CustomerAPITimeout, CustomerAPIUnavailable, CustomerAPIError):
        return jsonify({"error": "CUSTOMER_SERVICE_ERROR", "message": "Customer service lỗi."}), 503

    if not customer_service.check_currency_permission(customer, currency):
        return jsonify({"error": "CURRENCY_NOT_PERMITTED", "message": "Không được phép giao dịch currency này."}), 403
    if not customer_service.check_amount_limit(customer, amount_value):
        return jsonify({"error": "AMOUNT_LIMIT_EXCEEDED", "message": "Vượt hạn mức."}), 403

    try:
        base_price = market_rate_service.get_rate(currency=currency, side=side)
    except MarketRateError:
        return jsonify({"error": "BASE_PRICE_UNAVAILABLE", "message": "Market Rate không khả dụng."}), 503

    try:
        result = pricing_engine.calculate_price(
            customer=customer,
            currency=currency,
            side=side,
            amount=amount_value,
            base_price=base_price,
            branch_margin=branch_margin,
            viewer_role=role,
        )
    except PricingError as e:
        return jsonify({"error": "PRICING_ERROR", "message": str(e)}), 400

    quote_payload = {
        "currency": result["currency"],
        "side": result["side"],
        "price": result["price"],
        "tgdh": result.get("tgdh", result["price"]),
        "valid_for_seconds": result["valid_for_seconds"],
        "issued_at": result["issued_at"],
    }
    if role in {"PNV", "STAFF", "BRANCH"}:
        for k in ("branch_margin", "max_branch_margin"):
            if k in result:
                quote_payload[k] = result[k]
    if role == "HQ":
        for k in ("base_price", "hq_base_spread", "branch_margin",
                  "max_branch_margin", "pricing_tier", "total_spread", "tgdh_points"):
            if k in result:
                quote_payload[k] = result[k]

    return jsonify({"status": "success", "quote": quote_payload}), 200


@pricing_bp.route("/health", methods=["GET"])
def pricing_health():
    return jsonify({"status": "healthy", "service": "pricing-api", "timestamp": int(time.time())}), 200
