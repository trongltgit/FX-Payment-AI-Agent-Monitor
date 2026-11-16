"""Cổng thống nhất v2:  POST /gateway/v2/transaction
Xác thực bằng MỘT trong hai khóa: `Authorization: Bearer agk_…` (AI Agent) hoặc `X-Source-Key: skx_…` (hệ thống nguồn gửi giao dịch của NGƯỜI).
Luôn đi qua pipeline: Anti-Bot → Monitor. Phản hồi có trường `stage` cho biết dừng ở tầng nào."""
import time

from flask import Blueprint, jsonify, request

from agentmon import engine, pipeline, registry, sources
from services import bot_defense
from services.audit_log import add_log
from utils import store
from utils.security import get_client_ip

gw_bp = Blueprint("gateway_v2", __name__)


def _j(code, msg, status):
    return jsonify({"error": code, "message": msg}), status


@gw_bp.route("/gateway/v2/transaction", methods=["POST"])
def transaction():
    t0 = time.perf_counter()
    ip = get_client_ip()
    key_a = request.headers.get("Authorization", "")
    key_a = key_a[7:].strip() if key_a.lower().startswith("bearer ") else ""
    key_s = request.headers.get("X-Source-Key", "")
    agent = registry.by_key(key_a) if key_a else None
    src = sources.by_key(key_s) if (key_s and not agent) else None
    if not agent and not src:
        store.events_add(f"gw:bad:{ip}", "", keep_seconds=300)
        if store.events_count(f"gw:bad:{ip}", 300) > 10:
            return _j("RATE_LIMITED", "Quá nhiều lần sai khóa.", 429)
        bot_defense.ip_strike(ip, "gateway_bad_key", weight=2)
        add_log("gateway_key_invalid", ip=ip, level="warn")
        return _j("UNAUTHORIZED", "Thiếu hoặc sai khóa (Bearer agk_… hoặc X-Source-Key skx_…).", 401)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return _j("BAD_REQUEST", "Body phải là JSON object.", 400)
    if src and not body.get("request_id"):
        return _j("BAD_REQUEST", "Thiếu request_id.", 400)
    try:
        pr = pipeline.process(credential="AGENT_KEY" if agent else "SOURCE_KEY", body=body, ip=ip, ua=request.headers.get("User-Agent", ""),
                              source_system=(src or {}).get("source"), agent=agent, challenge_passed=bool((body.get("session") or {}).get("turnstile_ok")),
                              source="GATEWAY_V2")
    except engine.BadRequest as e:
        return _j("BAD_REQUEST", str(e), 400)
    ab = pr["antibot"]
    if pr["stage"] == "ANTIBOT":
        out = pipeline.antibot_response(ab)
        out["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
        return jsonify(out), (403 if ab["action"] == "BLOCK" else 200)
    r = pr["result"]
    out = {"stage": "MONITOR", "transaction_id": r["action_id"], "action": r["decision"], "status": r["status"], "message": r["reason_public"],
           "actor_type": pr["actor"]["actor_type"], "actor_confidence": pr["actor"]["confidence"], "bot_class": ab["bot_class"],
           "reason_codes": sorted({t[0] for t in (r.get("triggers") or []) if isinstance(t, (list, tuple))} | set(r.get("fraud_types") or [])),
           "elapsed_ms": int((time.perf_counter() - t0) * 1000)}
    if r["decision"] == "STEP_UP":
        out["step_up"] = {"method": "BIOMETRIC" if r.get("fraud_class") == "FRAUD_SUSPECTED" else "OTP", "expires_in": engine.STEPUP_HOLD_SECONDS,
                          "callback": f"/txn-api/v1/transactions/{r['action_id']}/step-up-result"}
    if r.get("kya"):
        out["kya"] = {"id": r["kya"]["id"], "expires_in": r["kya"]["expires_in"]}
    return jsonify(out), 200
