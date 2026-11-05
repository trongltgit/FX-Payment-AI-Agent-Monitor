"""
Cổng cho AI Agent thật (không dùng cookie):
  POST /agent-api/v1/monitor/action        Authorization: Bearer agk_xxx
  GET  /agent-api/v1/actions/<id>          polling kết quả KYA
Cổng cho ứng dụng Authenticator (thiết bị đã ghép):
  POST /authapp/pair      {pairing_code, pin, label}
  GET  /authapp/pending   Authorization: Bearer dev_xxx
  POST /authapp/decide    {kya_id, approve, pin}
Các đường dẫn này nằm ngoài /api nên có rate-limit + kiểm xác thực riêng (bearer, không CSRF vì không dùng cookie).
"""
from flask import Blueprint, jsonify, render_template, request

from agentmon import db, engine, kya, registry
from services.audit_log import add_log
from utils import store
from utils.security import get_client_ip

gateway_bp = Blueprint("agent_gateway", __name__)


def _bearer():
    h = request.headers.get("Authorization", "")
    return h[7:].strip() if h.lower().startswith("bearer ") else ""


def _limit(key, n, window):
    store.events_add(key, "", keep_seconds=window + 5)
    return store.events_count(key, window) > n


def _j(code, msg, status):
    return jsonify({"error": code, "message": msg}), status


@gateway_bp.route("/agent-api/v1/health")
def health():
    return jsonify({"status": "ok"})


@gateway_bp.route("/agent-api/v1/monitor/action", methods=["POST"])
def monitor_action():
    ip = get_client_ip()
    if _limit(f"agk:ip:{ip}", 300, 60):
        return _j("RATE_LIMITED", "Quá nhiều yêu cầu.", 429)
    key = _bearer()
    ag = registry.by_key(key)
    if not ag:
        if _limit(f"agk:bad:{ip}", 10, 300):
            return _j("RATE_LIMITED", "Quá nhiều lần sai khóa.", 429)
        store.events_add(f"agk:bad:{ip}", "", keep_seconds=300)
        add_log("agent_key_invalid", ip=ip, level="warn")
        return _j("UNAUTHORIZED", "API key không hợp lệ.", 401)
    if _limit(f"agk:key:{ag['agent_id']}", 120, 60):
        return _j("RATE_LIMITED", "Agent gửi quá nhanh (120/phút).", 429)
    raw = request.get_json(silent=True)
    if raw is None:
        return _j("BAD_REQUEST", "Body phải là JSON.", 400)
    try:
        r = engine.evaluate(raw, ag["agent_id"], source="AGENT_API", ip=ip)
    except engine.BadRequest as e:
        return _j("BAD_REQUEST", str(e), 400)
    out = {"action_id": r["action_id"], "decision": r["decision"], "status": r["status"], "message": r["reason_public"],
           "duplicate": r.get("duplicate", False)}
    if r.get("kya"):
        out["kya"] = {"id": r["kya"]["id"], "expires_in": r["kya"]["expires_in"],
                      "note": "Khách hàng phải duyệt trong ứng dụng Authenticator. Poll GET /agent-api/v1/actions/<id>."}
    if r["decision"] == "BLOCK" and r.get("hard_reason"):
        out["reason"] = r["hard_reason"]
    return jsonify(out), (200 if r["decision"] != "BLOCK" else 403)


@gateway_bp.route("/agent-api/v1/actions/<int:aid>", methods=["GET"])
def action_status(aid):
    ag = registry.by_key(_bearer())
    if not ag:
        return _j("UNAUTHORIZED", "API key không hợp lệ.", 401)
    kya.expire_stale()
    r = db.one("SELECT id, agent_id, decision, status, reason_public, executed_at FROM actions WHERE id=?", (aid,))
    if not r or r["agent_id"] != ag["agent_id"]:
        return _j("NOT_FOUND", "Không tìm thấy.", 404)
    r.pop("agent_id")
    return jsonify(r)


# ---------------- Authenticator app ----------------
@gateway_bp.route("/authenticator")
def authenticator_page():
    return render_template("authenticator.html")


@gateway_bp.route("/authapp/pair", methods=["POST"])
def app_pair():
    ip = get_client_ip()
    if _limit(f"authapp:pair:{ip}", 8, 300):
        return _j("RATE_LIMITED", "Thử quá nhiều lần. Đợi 5 phút.", 429)
    d = request.get_json(silent=True) or {}
    res, msg = kya.pair_device(str(d.get("pairing_code", "")), str(d.get("pin", "")), str(d.get("label", "")))
    if not res:
        add_log("authapp_pair_failed", ip=ip, level="warn")
        return _j("PAIR_FAILED", msg, 400)
    add_log("authapp_paired", customer_id=res["customer_id"], ip=ip, level="warn")
    return jsonify({"status": "success", "device_token": res["device_token"], "customer_id": res["customer_id"]})


@gateway_bp.route("/authapp/pending", methods=["GET"])
def app_pending():
    a = kya.device_by_token(_bearer())
    if not a:
        return _j("UNAUTHORIZED", "Thiết bị chưa ghép hoặc đã bị hủy.", 401)
    if _limit(f"authapp:poll:{a['customer_id']}", 120, 60):
        return _j("RATE_LIMITED", "Quá nhiều yêu cầu.", 429)
    return jsonify({"customer_id": a["customer_id"], "device": a.get("device_label"), "pending": kya.pending_for(a["customer_id"])})


@gateway_bp.route("/authapp/decide", methods=["POST"])
def app_decide():
    tok = _bearer()
    a = kya.device_by_token(tok)
    if not a:
        return _j("UNAUTHORIZED", "Thiết bị chưa ghép.", 401)
    d = request.get_json(silent=True) or {}
    ok, msg, res = kya.decide_device(tok, str(d.get("kya_id", "")), bool(d.get("approve")), str(d.get("pin", "")))
    add_log("authapp_decision", customer_id=a["customer_id"], ip=get_client_ip(), level="warn",
            detail={"kya": d.get("kya_id"), "approve": bool(d.get("approve")), "ok": ok})
    return jsonify({"status": "success", "result": res}) if ok else _j("DECIDE_FAILED", msg, 400)
