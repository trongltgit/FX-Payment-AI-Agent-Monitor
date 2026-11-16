"""API cho HỆ THỐNG NGUỒN gửi giao dịch của NGƯỜI dùng để chấm điểm rủi ro theo thời gian thực.

  POST /txn-api/v1/monitor/transaction            X-Source-Key: skx_xxx   → quyết định ngay (đồng bộ)
  POST /txn-api/v1/transactions/<id>/step-up-result                       → báo kết quả OTP/sinh trắc
  GET  /txn-api/v1/transactions/<id>

Hệ thống nguồn: PORTAL, DIGIBANK, DIGIBIZ, CARD_SWITCH, ATM_SWITCH, IPS_TRANSFER (mỗi hệ thống một khóa, chỉ gửi đúng loại giao dịch của nguồn đó).
Đường đi nhanh: KHÔNG gọi LLM; quyết định ∈ ALLOW | STEP_UP | REVIEW | BLOCK. Kênh nguồn (core/switch) là bên THỰC HIỆN hoặc từ chối giao dịch
theo quyết định; Monitor không điều khiển core banking (trong bản demo, ALLOW trừ số dư mô phỏng).
Không trả điểm số nội bộ cho kênh nguồn; chỉ trả mã lý do (trigger/loại gian lận) để kênh hiển thị/ghi nhận.
"""
import time

from flask import Blueprint, jsonify, request

from agentmon import db, engine, pipeline, sources
from services import bot_defense
from services.audit_log import add_log
from utils import store
from utils.security import get_client_ip

txn_bp = Blueprint("txn_gateway", __name__)


def _limit(key, n, window):
    store.events_add(key, "", keep_seconds=window + 5)
    return store.events_count(key, window) > n


def _j(code, msg, status):
    return jsonify({"error": code, "message": msg}), status


def _auth():
    key = request.headers.get("X-Source-Key", "")
    return sources.by_key(key)


def _step_up_method(r):
    m = ((r.get("details") or {}).get("atm_identity") or {}).get("step_up_method")
    if m:
        return m          # ATM: APP_CONFIRM = chủ thẻ xác nhận trên điện thoại (KYA của kênh ATM)
    # Sinh trắc khi nghi gian lận hoặc phiên có điểm bot không thấp; còn lại OTP
    if r.get("fraud_class") == "FRAUD_SUSPECTED" or (r.get("details") or {}).get("session_risk", 0) >= 0.4:
        return "BIOMETRIC"
    return "OTP"


def _out(r, t0=None):
    out = {"transaction_id": r["action_id"], "action": r["decision"], "status": r["status"], "message": r["reason_public"],
           "duplicate": r.get("duplicate", False),
           "reason_codes": sorted({t[0] for t in (r.get("triggers") or []) if isinstance(t, (list, tuple))} | set(r.get("fraud_types") or [])),
           "fraud_class": r.get("fraud_class")}
    if r["decision"] == "STEP_UP":
        out["step_up"] = {"method": _step_up_method(r), "expires_in": engine.STEPUP_HOLD_SECONDS,
                          "callback": f"/txn-api/v1/transactions/{r['action_id']}/step-up-result"}
    if r["decision"] == "BLOCK" and r.get("hard_reason"):
        out["reason"] = r["hard_reason"]
    if r.get("details", {}).get("pre_screen"):
        ps = r["details"]["pre_screen"]
        out["screening"] = {"bot_class": ps["antibot"]["bot_class"], "actor_type": ps["actor"]["actor_type"], "actor_confidence": ps["actor"]["confidence"]}
    if t0 is not None:
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return out


@txn_bp.route("/txn-api/v1/health")
def health():
    return jsonify({"status": "ok"})


@txn_bp.route("/txn-api/v1/monitor/transaction", methods=["POST"])
def monitor_transaction():
    t0 = time.perf_counter()
    ip = get_client_ip()
    if _limit(f"skx:ip:{ip}", 3000, 60):
        return _j("RATE_LIMITED", "Quá nhiều yêu cầu.", 429)
    src = _auth()
    if not src:
        if _limit(f"skx:bad:{ip}", 10, 300):
            return _j("RATE_LIMITED", "Quá nhiều lần sai khóa.", 429)
        store.events_add(f"skx:bad:{ip}", "", keep_seconds=300)
        bot_defense.ip_strike(ip, "source_bad_key", weight=2)
        add_log("source_key_invalid", ip=ip, level="warn")
        return _j("UNAUTHORIZED", "X-Source-Key không hợp lệ.", 401)
    if _limit(f"skx:key:{src['system_id']}", 6000, 60):
        return _j("RATE_LIMITED", "Hệ thống nguồn gửi quá nhanh.", 429)
    raw = request.get_json(silent=True)
    if not isinstance(raw, dict):
        return _j("BAD_REQUEST", "Body phải là JSON object.", 400)
    cid = str(raw.get("customer_id", "")).strip()
    if not cid:
        return _j("BAD_REQUEST", "Thiếu customer_id.", 400)
    if not raw.get("request_id"):
        return _j("BAD_REQUEST", "Thiếu request_id (mã giao dịch duy nhất của kênh nguồn, dùng chống gửi trùng).", 400)
    sess = raw.get("session") if isinstance(raw.get("session"), dict) else {}
    body = dict(raw)
    body.setdefault("device_id", sess.get("device_id"))
    body.setdefault("session_risk", sess.get("anti_bot_score", 0))
    try:
        pr = pipeline.process(credential="SOURCE_KEY", body=body, ip=ip, ua=request.headers.get("User-Agent", ""), source_system=src["source"],
                              header_score=int(sess.get("header_score") or 0), challenge_passed=bool(sess.get("turnstile_ok")), source="TXN_API")
    except engine.BadRequest as e:
        return _j("BAD_REQUEST", str(e), 400)
    if pr["stage"] == "ANTIBOT":                      # tầng 1 dừng: bot bị chặn / cần thử thách → kênh nguồn xử lý, Monitor không chạy
        out = pipeline.antibot_response(pr["antibot"])
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        return jsonify(out), 200
    r = pr["result"]
    return jsonify(_out(r, t0)), 200


@txn_bp.route("/txn-api/v1/transactions/<int:aid>/step-up-result", methods=["POST"])
def step_up_result(aid):
    src = _auth()
    if not src:
        return _j("UNAUTHORIZED", "X-Source-Key không hợp lệ.", 401)
    raw = request.get_json(silent=True) or {}
    if "passed" not in raw or not isinstance(raw["passed"], bool):
        return _j("BAD_REQUEST", "Thiếu trường boolean 'passed'.", 400)
    out = engine.step_up_result(aid, raw["passed"], src["source"])
    if out["status"] in ("NOT_FOUND", "FORBIDDEN"):
        return _j(out["status"], "Không tìm thấy giao dịch của hệ thống nguồn này.", 404)
    return jsonify({"transaction_id": aid, "status": out["status"], "reason": out.get("reason")})


@txn_bp.route("/txn-api/v1/transactions/<int:aid>", methods=["GET"])
def get_txn(aid):
    src = _auth()
    if not src:
        return _j("UNAUTHORIZED", "X-Source-Key không hợp lệ.", 401)
    row = db.one("SELECT source_system FROM actions WHERE id=? AND actor_type='HUMAN'", (aid,))
    if not row or row["source_system"] != src["source"]:
        return _j("NOT_FOUND", "Không tìm thấy giao dịch.", 404)
    return jsonify(_out(engine.get_action_result(aid)))
