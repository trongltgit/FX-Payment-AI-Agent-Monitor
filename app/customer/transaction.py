"""
Transaction API – HQ / CN_ADMIN / PNV / CUSTOMER
"""

import json
import os
import time
import uuid

from flask import Blueprint, request, jsonify, session, g

from app.middleware import pricing_security_required, auth_required
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
from services import bot_defense, quote_store
from services.market_rate import market_rate_service, MarketRateError
from services.pricing_engine import pricing_engine, PricingError
from services.audit_log import (
    add_log, list_logs,
    check_same_param_cooldown, get_cif_quote_version, bump_cif_quote_version,
    logs_to_csv, claim_quote,
)
from utils import pow as pow_mod
from utils import store
from utils.rate_limit import custom_rate_limit, user_rate_limit
from utils.security import get_client_ip

transaction_bp = Blueprint(
    "transaction", __name__, url_prefix="/api/transaction"
)

customer_service = CustomerService()
_TRANSACTIONS = []   # RAM – production: ghi PostgreSQL (khóa UNIQUE trên quote_id). Xem TXN_LOG_FILE.

STAFF_ROLES = {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}


def _current_user():
    return {
        "user_id": session.get("user_id"),
        "role": session.get("role"),
        "customer_id": session.get("customer_id"),
        "permitted_customers": session.get("permitted_customers") or [],
        "branch_id": session.get("branch_id") or "",
    }


def _append_txn_file(txn: dict) -> None:
    """Ghi giao dịch append-only ra JSON Lines nếu cấu hình TXN_LOG_FILE (tạm thời trước khi có DB)."""
    path = os.environ.get("TXN_LOG_FILE", "").strip()
    if path:
        try:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(txn, ensure_ascii=False) + "\n")
        except OSError:
            pass


def _challenge_passed() -> bool:
    cid = request.headers.get("X-Challenge-Id", "")
    nonce = request.headers.get("X-Challenge-Nonce")
    if not cid:
        return False
    ok, _ = pow_mod.verify(cid, nonce, bind=get_client_ip(), min_bits=pow_mod.default_bits() + 2)
    return ok


def _enforce(d, *, user_id, role, customer_id="", ip="", use_window=True):
    """
    Áp quyết định của Bot Defense Engine. Trả về Response nếu phải chặn, None nếu cho qua.
      window soft  -> thu hồi phiên thật sự (server-side) + đánh dấu rủi ro; tái phạm 3 lần/10 phút -> khóa
      window hard  -> khóa tài khoản + thu hồi mọi phiên
      block        -> khóa
      throttle     -> 429 + Retry-After
      challenge    -> 428, client phải giải PoW rồi gửi lại
    """
    from app.customer.mock_db import block_user

    def _lock(why):
        block_user(user_id, why, blocked_by="system")
        add_log("bot_blocked", user_id=user_id, role=role, customer_id=customer_id, ip=ip,
                level="critical", detail={"score": d.score, "reasons": d.reasons, "why": why})
        session.clear()
        return jsonify({
            "error": "BLOCKED",
            "message": "Phát hiện hành vi bot. Tài khoản bị khóa. Liên hệ TSC để mở khóa.",
            "redirect": "/blocked",
        }), 403

    if use_window and d.window_hit == "hard":
        return _lock("quote_flood_bot")
    if d.action == "block":
        return _lock("bot_behavior_score")
    if use_window and d.window_hit == "soft":
        n = store.incr(f"viol:{user_id}", 600)
        if n >= 3:
            return _lock("repeated_soft_limit")
        store.set(f"risk:chal:{user_id}", "1", ttl=3600)
        add_log("force_relogin", user_id=user_id, role=role, customer_id=customer_id, ip=ip, level="warn",
                detail={"violations_10m": n})
        session.clear()
        return jsonify({
            "error": "SESSION_EXPIRED",
            "message": "Bạn đã hỏi giá quá nhiều lần. Vui lòng đăng nhập lại.",
            "redirect": "/",
        }), 401
    if d.action == "throttle":
        add_log("quote_throttled", user_id=user_id, role=role, customer_id=customer_id, ip=ip, level="warn",
                detail={"score": d.score, "reasons": d.reasons})
        resp = jsonify({
            "error": "QUOTE_THROTTLED",
            "message": "Bạn đã hỏi giá quá nhiều. Vui lòng thử lại sau.",
            "retry_after_seconds": d.retry_after,
        })
        resp.status_code = 429
        resp.headers["Retry-After"] = str(d.retry_after)
        return resp
    if d.action == "challenge" and not _challenge_passed():
        add_log("quote_challenge", user_id=user_id, role=role, customer_id=customer_id, ip=ip, level="info",
                detail={"score": d.score, "reasons": d.reasons})
        resp = jsonify({
            "error": "CHALLENGE_REQUIRED",
            "message": "Cần xác minh trước khi tiếp tục.",
            "challenge": pow_mod.issue(bits=pow_mod.default_bits() + 2, bind=ip),
        })
        resp.status_code = 428
        return resp
    return None


@transaction_bp.route("/quote", methods=["POST"])
@custom_rate_limit("30 per minute")
@user_rate_limit("20 per minute")
@pricing_security_required
def transaction_quote():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({
            "error": "AUTHENTICATION_REQUIRED",
            "message": "Yêu cầu đăng nhập.",
        }), 401

    data = request.get_json(silent=True) or {}
    currency = str(data.get("currency", "")).upper().strip()
    side = str(data.get("side", "")).upper().strip()
    amount = data.get("amount")
    branch_margin = data.get("branch_margin", 0)
    use_nsdh = bool(data.get("use_nsdh", False))
    nsdh_points = data.get("nsdh_points", 0)
    ip = get_client_ip()

    if not currency or not side or amount is None:
        return jsonify({
            "error": "INVALID_REQUEST",
            "message": "Thiếu currency, side hoặc amount.",
        }), 400

    try:
        amount_value = float(amount)
    except (TypeError, ValueError):
        return jsonify({
            "error": "INVALID_AMOUNT",
            "message": "Amount không hợp lệ.",
        }), 400

    if amount_value <= 0:
        return jsonify({
            "error": "INVALID_AMOUNT",
            "message": "Amount phải lớn hơn 0.",
        }), 400

    role = (session.get("role") or "CUSTOMER").upper()
    # KH: KHÔNG bao giờ tin customer_id từ client – chỉ lấy từ phiên đã xác thực
    if role == "CUSTOMER":
        customer_id = session.get("customer_id")
    else:
        customer_id = data.get("customer_id") or session.get("customer_id")
    if not customer_id:
        return jsonify({
            "error": "CUSTOMER_CONTEXT_REQUIRED",
            "message": "Chưa chọn khách hàng (CIF).",
        }), 403

    user = _current_user()

    # ---- Bot Defense: quota giờ/ngày + điểm hành vi nhiều cửa sổ thời gian
    decision = bot_defense.assess(
        user_id, role, ip,
        header_score=getattr(g, "header_score", 0),
        login_risk=int(session.get("login_risk", 0) or 0),
        pending=1,
    )
    blocked_resp = _enforce(decision, user_id=user_id, role=role, customer_id=customer_id, ip=ip)
    if blocked_resp is not None:
        return blocked_resp

    if role == "CUSTOMER":
        # (đặt SAU bước chấm điểm để yêu cầu bị challenge không 'đốt' cooldown của chính nó)
    # Cùng ccy + side + NHÓM số tiền bấm liên tục -> chặn 1 phút (đổi amount 0,01 không né được)
        remain = check_same_param_cooldown(user_id, currency, side, amount_value, 60)
        if remain is not None:
            store.events_add(f"cdhit:{user_id}", "1", keep_seconds=900)
            add_log(
                "quote_cooldown",
                user_id=user_id, role=role, customer_id=customer_id, ip=ip, level="warn",
                detail={"currency": currency, "side": side, "amount": amount_value, "remain": remain},
            )
            return jsonify({
                "error": "QUOTE_COOLDOWN",
                "message": "Hiện tại hệ thống không cập nhật giá được, xin vui lòng thử lại sau.",
                "retry_after_seconds": remain,
            }), 429

    bot_defense.record_quote(user_id, role, ip, currency, side, amount_value)
    add_log(
        "quote_request",
        user_id=user_id, role=role, customer_id=customer_id,
        branch_id=user.get("branch_id", ""), ip=ip,
        detail={"currency": currency, "side": side, "amount": amount_value, "risk_score": decision.score},
    )

    if not customer_service.check_user_access(user, customer_id):
        return jsonify({
            "error": "ACCESS_DENIED",
            "message": "Bạn không có quyền giao dịch CIF này.",
        }), 403

    # KH: lấy margin + nsdh từ preset CN đã set
    if role == "CUSTOMER":
        branch_margin = 0
        use_nsdh = False
        nsdh_points = 0
        try:
            from services.cn_margin_store import get_preset
            preset = get_preset(customer_id, currency, side, amount)
            if preset:
                branch_margin = preset["margin"]
                use_nsdh = bool(preset.get("use_nsdh"))
                nsdh_points = preset.get("nsdh_points", 0)
            else:
                return jsonify({
                    "error": "WAITING_CN_SETUP",
                    "message": "Chưa có báo giá từ chi nhánh. Vui lòng liên hệ CN hoặc thử lại sau.",
                }), 403
        except Exception:
            return jsonify({
                "error": "WAITING_CN_SETUP",
                "message": "Chưa có báo giá từ chi nhánh. Vui lòng liên hệ CN hoặc thử lại sau.",
            }), 403

    try:
        customer = customer_service.get_customer(customer_id)
    except CustomerNotFound:
        return jsonify({"error": "CUSTOMER_NOT_FOUND", "message": "Không tìm thấy khách hàng."}), 404
    except CustomerInactive:
        return jsonify({"error": "CUSTOMER_INACTIVE", "message": "Khách hàng không hoạt động."}), 403
    except (CustomerAPITimeout, CustomerAPIUnavailable, CustomerAPIError) as e:
        return jsonify({"error": "CUSTOMER_SERVICE_ERROR", "message": str(e)}), 503

    if role == "CUSTOMER" and not customer.get("online", False):
        return jsonify({
            "error": "CIF_OFFLINE",
            "message": "CIF chưa được chi nhánh bật online. Vui lòng liên hệ CN.",
        }), 403

    if not customer_service.check_currency_permission(customer, currency):
        return jsonify({
            "error": "CURRENCY_NOT_PERMITTED",
            "message": "Khách hàng không được phép giao dịch currency này.",
        }), 403

    if not customer_service.check_amount_limit(customer, amount_value):
        return jsonify({
            "error": "AMOUNT_LIMIT_EXCEEDED",
            "message": "Amount vượt hạn mức khách hàng.",
        }), 403

    try:
        base_price = market_rate_service.get_rate(currency=currency, side=side)
    except MarketRateError:
        return jsonify({
            "error": "BASE_PRICE_UNAVAILABLE",
            "message": "Base price HQ không khả dụng.",
        }), 503

    try:
        result = pricing_engine.calculate_price(
            customer=customer,
            currency=currency,
            side=side,
            amount=amount_value,
            base_price=base_price,
            branch_margin=branch_margin,
            viewer_role=role,
            use_nsdh=use_nsdh,
            nsdh_points=nsdh_points,
        )
    except PricingError as e:
        return jsonify({"error": "PRICING_ERROR", "message": str(e)}), 400

    quote_id = str(uuid.uuid4())
    # KH online: giá giữ 60s; CN interrupt (đổi margin/NSDH) làm hết hiệu lực
    valid_secs = 60 if role == "CUSTOMER" else result["valid_for_seconds"]
    cif_ver = get_cif_quote_version(customer_id)
    quote_store.save(quote_id, {
        "quote_id": quote_id,
        "user_id": user_id,
        "sid": getattr(session, "sid", ""),
        "currency": result["currency"],
        "side": result["side"],
        "price": result["price"],
        "tgdh": result.get("tgdh"),
        "use_nsdh": result.get("use_nsdh", False),
        "nsdh_points": result.get("nsdh_points", "0"),
        "amount": amount_value,
        "branch_margin": result.get("branch_margin") or result.get("_branch_margin", "0"),
        "customer_id": customer_id,
        "issued_at": result["issued_at"],
        "valid_for_seconds": valid_secs,
        "cif_version": cif_ver,
        "base_price": result.get("base_price"),
        "hq_base_spread": result.get("hq_base_spread"),
    }, valid_secs)
    result = dict(result)
    result["valid_for_seconds"] = valid_secs

    quote_payload = {
        "quote_id": quote_id,
        "currency": result["currency"],
        "side": result["side"],
        "price": result["price"],
        "amount": amount_value,
        "valid_for_seconds": result["valid_for_seconds"],
        "issued_at": result["issued_at"],
    }

    # CN: final + margin CN + tgdh (nếu chọn NSDH) + trần margin CN
    if role in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
        quote_payload["branch_margin"] = result.get("branch_margin", "0")
        if result.get("max_cn_margin"):
            quote_payload["max_cn_margin"] = result["max_cn_margin"]
        if result.get("use_nsdh"):
            quote_payload["tgdh"] = result["tgdh"]
            quote_payload["nsdh_points"] = result.get("nsdh_points", "0")
            quote_payload["use_nsdh"] = True

    # HQ: full trừ margin CN (chỉ sau deal)
    if role == "HQ":
        for k in ("base_price", "hq_base_spread", "tgdh", "nsdh_points", "use_nsdh",
                  "pricing_tier", "total_spread"):
            if k in result and result[k] is not None:
                quote_payload[k] = result[k]

    return jsonify({"status": "success", "quote": quote_payload}), 200


@transaction_bp.route("/quote-batch", methods=["POST"])
@custom_rate_limit("15 per minute")
@user_rate_limit("10 per minute")
@pricing_security_required
def transaction_quote_batch():
    """
    CN: xem giá nhiều CIF / nhiều ccy / mua-bán cùng lúc (offline + online).
    Body: { "items": [ {customer_id, currency, side, amount, branch_margin, use_nsdh, nsdh_points}, ... ] }
    """
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({"error": "AUTHENTICATION_REQUIRED", "message": "Yêu cầu đăng nhập."}), 401

    role = (session.get("role") or "").upper()
    if role not in {"PNV", "STAFF", "BRANCH", "CN_ADMIN", "HQ"}:
        return jsonify({"error": "FORBIDDEN", "message": "Chỉ CN/HQ dùng batch quote."}), 403

    data = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "INVALID", "message": "Thiếu items[]."}), 400
    max_items = int(os.environ.get("BATCH_MAX_ITEMS", "50"))
    if len(items) > max_items:
        return jsonify({"error": "TOO_MANY", "message": f"Tối đa {max_items} dòng / lần."}), 400

    # Mỗi dòng batch tiêu thụ 1 lượt trong quota giờ/ngày (batch không còn là đường vòng để cào giá)
    ip = get_client_ip()
    decision = bot_defense.assess(
        user_id, role, ip,
        header_score=getattr(g, "header_score", 0),
        login_risk=int(session.get("login_risk", 0) or 0),
        pending=len(items),
    )
    blocked_resp = _enforce(decision, user_id=user_id, role=role, ip=ip, use_window=False)
    if blocked_resp is not None:
        return blocked_resp
    bot_defense.record_quote(user_id, role, ip, "BATCH", "MIX", 0, count=len(items))

    user = _current_user()
    results = []
    for raw in items:
        cid = str(raw.get("customer_id") or "").strip()
        currency = str(raw.get("currency", "")).upper().strip()
        side = str(raw.get("side", "")).upper().strip()
        amount = raw.get("amount")
        branch_margin = raw.get("branch_margin", 0)
        use_nsdh = bool(raw.get("use_nsdh", False))
        nsdh_points = raw.get("nsdh_points", 0)
        row = {"customer_id": cid, "currency": currency, "side": side, "amount": amount}

        if not cid or not currency or not side or amount is None:
            row["error"] = "Thiếu trường"
            results.append(row)
            continue
        if not customer_service.check_user_access(user, cid):
            row["error"] = "Không có quyền CIF"
            results.append(row)
            continue
        try:
            amount_value = float(amount)
            if amount_value <= 0:
                raise ValueError()
        except (TypeError, ValueError):
            row["error"] = "Amount không hợp lệ"
            results.append(row)
            continue

        try:
            customer = customer_service.get_customer(cid)
            base_price = market_rate_service.get_rate(currency=currency, side=side)
            result = pricing_engine.calculate_price(
                customer=customer,
                currency=currency,
                side=side,
                amount=amount_value,
                base_price=base_price,
                branch_margin=branch_margin,
                viewer_role="PNV",
                use_nsdh=use_nsdh,
                nsdh_points=nsdh_points,
            )
            row["price"] = result["price"]
            row["branch_margin"] = result.get("branch_margin", "0")
            row["max_cn_margin"] = result.get("max_cn_margin")
            if result.get("use_nsdh"):
                row["tgdh"] = result.get("tgdh")
                row["nsdh_points"] = result.get("nsdh_points")
                row["use_nsdh"] = True
            row["valid_for_seconds"] = result["valid_for_seconds"]
            row["issued_at"] = result["issued_at"]
        except Exception as e:
            row["error"] = str(e)
        results.append(row)

    add_log(
        "quote_batch",
        user_id=user_id, role=role,
        branch_id=user.get("branch_id", ""),
        ip=get_client_ip(),
        detail={"count": len(items)},
    )
    return jsonify({"status": "success", "quotes": results}), 200


@transaction_bp.route("/execute", methods=["POST"])
@custom_rate_limit("10 per minute")
@user_rate_limit("8 per minute")
@pricing_security_required
def transaction_execute():
    user_id = session.get("user_id")
    if not user_id:
        return jsonify({
            "error": "AUTHENTICATION_REQUIRED",
            "message": "Yêu cầu đăng nhập.",
        }), 401

    data = request.get_json(silent=True) or {}
    quote_id = str(data.get("quote_id", "")).strip()
    last_quote = quote_store.load(quote_id)

    # Quote nằm ở server: phải đúng chủ sở hữu VÀ đúng phiên đã hỏi giá
    if (not last_quote
            or last_quote.get("user_id") != user_id
            or last_quote.get("sid") != getattr(session, "sid", None)):
        return jsonify({
            "error": "INVALID_QUOTE",
            "message": "Quote không hợp lệ hoặc đã hết hạn.",
        }), 400

    if int(time.time()) - last_quote.get("issued_at", 0) > last_quote.get("valid_for_seconds", 60):
        return jsonify({
            "error": "QUOTE_EXPIRED",
            "message": "Quote đã hết hạn (quá 1 phút). Vui lòng lấy giá mới.",
        }), 400

    # CN đổi margin/NSDH → interrupt
    if last_quote.get("cif_version", 0) != get_cif_quote_version(last_quote.get("customer_id") or ""):
        return jsonify({
            "error": "QUOTE_INTERRUPTED",
            "message": "Chi nhánh đã thay đổi margin/NSDH. Giá hết hiệu lực. Vui lòng lấy giá mới.",
        }), 400

    customer_id = last_quote.get("customer_id")
    user = _current_user()
    if not customer_service.check_user_access(user, customer_id):
        return jsonify({
            "error": "ACCESS_DENIED",
            "message": "Không có quyền thực hiện giao dịch.",
        }), 403

    # P0: Quote chỉ được execute một lần (chống replay cookie)
    if not claim_quote(quote_id):
        return jsonify({
            "error": "QUOTE_ALREADY_USED",
            "message": "Quote đã được sử dụng.",
        }), 409

    txn_id = f"TXN{int(time.time())}{uuid.uuid4().hex[:6].upper()}"
    txn = {
        "transaction_id": txn_id,
        "quote_id": quote_id,
        "customer_id": customer_id,
        "user_id": user_id,
        "branch_id": user.get("branch_id", ""),
        "currency": last_quote["currency"],
        "side": last_quote["side"],
        "amount": last_quote["amount"],
        "price": last_quote["price"],
        "tgdh": last_quote.get("tgdh"),
        "use_nsdh": last_quote.get("use_nsdh", False),
        "nsdh_points": last_quote.get("nsdh_points", "0"),
        "branch_margin": last_quote.get("branch_margin", "0"),
        "base_price": last_quote.get("base_price"),
        "hq_base_spread": last_quote.get("hq_base_spread"),
        "status": "COMPLETED",
        "created_at": int(time.time()),
    }
    _TRANSACTIONS.append(txn)
    bot_defense.record_execute(user_id)
    _append_txn_file(txn)

    add_log(
        "deal_done",
        user_id=user_id,
        role=(session.get("role") or ""),
        customer_id=customer_id,
        branch_id=user.get("branch_id", ""),
        ip=get_client_ip(),
        detail={"txn": txn_id, "price": txn["price"], "margin": txn["branch_margin"]},
    )

    role = (session.get("role") or "").upper()
    txn_view = {
        "transaction_id": txn_id,
        "currency": txn["currency"],
        "side": txn["side"],
        "amount": txn["amount"],
        "price": txn["price"],
        "status": txn["status"],
        "created_at": txn["created_at"],
    }
    if role in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
        txn_view["branch_margin"] = txn["branch_margin"]
        if txn.get("use_nsdh"):
            txn_view["tgdh"] = txn.get("tgdh")
            txn_view["nsdh_points"] = txn.get("nsdh_points")
    if role == "HQ":
        txn_view["branch_margin"] = txn["branch_margin"]
        txn_view["base_price"] = txn.get("base_price")
        txn_view["tgdh"] = txn.get("tgdh")
        txn_view["nsdh_points"] = txn.get("nsdh_points")
        txn_view["hq_base_spread"] = txn.get("hq_base_spread")

    return jsonify({"status": "success", "transaction": txn_view}), 200


@transaction_bp.route("/history", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
def transaction_history():
    user_id = session.get("user_id")
    customer_id = session.get("customer_id")
    role = (session.get("role") or "").upper()
    branch_id = session.get("branch_id") or ""

    if role == "HQ":
        items = list(_TRANSACTIONS)
    elif role == "CN_ADMIN":
        items = [t for t in _TRANSACTIONS if t.get("branch_id") == branch_id]
    else:
        items = [
            t for t in _TRANSACTIONS
            if t.get("user_id") == user_id or t.get("customer_id") == customer_id
        ]

    safe = []
    for t in items[-50:]:
        row = {
            "transaction_id": t["transaction_id"],
            "currency": t["currency"],
            "side": t["side"],
            "amount": t["amount"],
            "price": t["price"],
            "status": t["status"],
            "created_at": t["created_at"],
            "customer_id": t.get("customer_id"),
        }
        if role in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
            row["branch_margin"] = t.get("branch_margin", "0")
            if t.get("use_nsdh"):
                row["tgdh"] = t.get("tgdh")
        if role == "HQ":
            row["branch_margin"] = t.get("branch_margin", "0")
            row["base_price"] = t.get("base_price")
            row["tgdh"] = t.get("tgdh")
        safe.append(row)
    return jsonify({"status": "success", "transactions": safe}), 200


@transaction_bp.route("/audit-logs", methods=["GET"])
@custom_rate_limit("20 per minute")
@auth_required
def audit_logs():
    role = (session.get("role") or "").upper()
    if role not in {"HQ", "CN_ADMIN"}:
        return jsonify({"error": "FORBIDDEN", "message": "Chỉ TSC hoặc Admin CN xem log."}), 403
    logs = list_logs(
        role_viewer=role,
        branch_id=session.get("branch_id") or "",
        user_id=session.get("user_id") or "",
        limit=200,
    )
    return jsonify({"status": "success", "logs": logs}), 200
