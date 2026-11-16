"""LUỒNG XỬ LÝ DUY NHẤT – bảo đảm THỨ TỰ: ANTI-BOT (tầng 1) → AI AGENT MONITOR (tầng 2). Mọi cửa vào gọi process().

  1. antibot_txn.assess()  – bot thật hay người/Agent hợp lệ?  BLOCK/CHALLENGE → dừng, KHÔNG gọi Monitor.
  2. actor.classify()      – người thực hiện là AI Agent hay NGƯỜI (độ tin cậy; không rõ → ACTOR_UNVERIFIED).
  3. engine.evaluate()     – Hard Policy → ML + Hành vi + Velocity → Trigger → (LLM chỉ cho Agent) → ALLOW/KYA|STEP_UP/REVIEW/BLOCK.
"""
from agentmon import actor as actor_mod
from agentmon import antibot_txn, cardmodel, db, engine
from agentmon.constants import CARD_KINDS
from services import bot_defense

import hashlib


def _card_ref(body):
    t = body.get("card_token")
    return hashlib.sha256(str(t).encode()).hexdigest()[:16] if t else None


def _amount(body):
    try:
        return float(body.get("amount_vnd") or (float(body.get("notional_usd") or 0) * engine.usd_vnd()))
    except (TypeError, ValueError):
        return 0.0


_REPUTATION = ("", None, "CLEAN", "TOR", "PROXY", "DATACENTER", "RESIDENTIAL")


def _validate_session(s):
    """Kiểm tra tín hiệu phiên do kênh nguồn gửi (đầu vào KHÔNG tin cậy tuyệt đối): sai kiểu/khoảng giá trị → 400."""
    def num(k, lo, hi):
        v = s.get(k)
        if v is None:
            return
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise engine.BadRequest(f"session.{k} phải là số.")
        if not lo <= f <= hi:
            raise engine.BadRequest(f"session.{k} phải nằm trong {lo}–{hi}.")
    num("anti_bot_score", 0, 100)
    num("think_time_ms", 0, 3_600_000)
    num("pointer_events", 0, 10 ** 6)
    num("key_events", 0, 10 ** 6)
    num("mfa_age_s", 0, 10 ** 7)
    num("header_score", 0, 100)
    num("pointer_path_entropy", 0, 1)
    num("key_interval_cv", 0, 10)
    num("scroll_events", 0, 10 ** 6)
    num("focus_changes", 0, 10 ** 4)
    num("session_age_s", 0, 10 ** 8)
    if s.get("ip_reputation") not in _REPUTATION:
        raise engine.BadRequest("session.ip_reputation không hợp lệ.")
    for k in ("device_attested", "device_known", "pow_ok", "turnstile_ok"):
        if k in s and not isinstance(s[k], bool):
            raise engine.BadRequest(f"session.{k} phải là boolean.")


def process(*, credential, body, ip, ua="", header_score=0, source_system=None, agent=None, challenge_passed=False, source="GATEWAY"):
    """Trả {"stage": "ANTIBOT"|"MONITOR", "antibot": {...}, "actor": {...}|None, "result": dict|None}. Có thể ném engine.BadRequest."""
    ses = body.get("session") if isinstance(body.get("session"), dict) else {}
    _validate_session(ses)
    cid = (agent or {}).get("customer_id") if agent else str(body.get("customer_id", "")).strip()
    client_ip = ses.get("client_ip") or ip                      # IP thật của khách (nguồn gửi hộ) – không phải IP máy chủ ngân hàng
    ses = dict(ses)
    if challenge_passed:
        ses["turnstile_ok"] = True
    ses.setdefault("device_id", body.get("device_id"))
    bio = body.get("biometric")
    if isinstance(bio, dict):          # chỉ tín hiệu vô hướng sang Tầng 1 (embedding KHÔNG đi qua)
        ses["biometric"] = {k: v for k, v in bio.items() if k != "face_embedding"}
    req = {"challenge_passed": challenge_passed, "credential": credential, "ip": client_ip, "ua": ua, "header_score": header_score, "source_system": source_system,
           "agent_id": (agent or {}).get("agent_id"), "session": ses,
           "txn": {"customer_id": cid, "kind": str(body.get("kind", "")).upper(), "domain": str(body.get("domain", "")).upper(),
                   "amount": _amount(body), "card_ref": _card_ref(body)}}
    # ---------------- TẦNG 1: Anti-Bot ----------------
    try:
        ab = antibot_txn.assess(req)
    except Exception as e:      # noqa: BLE001
        if antibot_txn.cfg()["fail_closed"]:
            ab = {"bot_class": antibot_txn.SUSPECT, "bot_score": 60, "action": antibot_txn.BLOCK, "declared_actor": "AGENT" if credential == "AGENT_KEY" else "HUMAN",
                  "bot_points": 0, "human_points": 0, "rules": ["ANTIBOT_ERROR"], "evidence": [], "note": f"Lỗi hệ thống chống bot (fail-closed): {str(e)[:60]}",
                  "challenge": None, "observed_automation": False}
        else:
            ab = {"bot_class": antibot_txn.HUMAN_LIKELY, "bot_score": 0, "action": antibot_txn.ALLOW, "declared_actor": "AGENT" if credential == "AGENT_KEY" else "HUMAN",
                  "bot_points": 0, "human_points": 0, "rules": ["ANTIBOT_ERROR_FAIL_OPEN"], "evidence": [], "note": "Lỗi chống bot (fail-open, chỉ demo)",
                  "challenge": None, "observed_automation": False}
    if ab["action"] != antibot_txn.ALLOW:
        antibot_txn.persist(req, ab)
        if ab["bot_class"] == antibot_txn.MALICIOUS_BOT and ab["declared_actor"] == "HUMAN" and ses.get("client_ip"):
            bot_defense.ip_strike(client_ip, "txn_bot:" + (ab["rules"][0] if ab["rules"] else "bot"), weight=2)     # chỉ IP khách; không bao giờ IP máy chủ nguồn
        antibot_txn.record_outcome(req, declined=True)
        return {"stage": "ANTIBOT", "antibot": ab, "actor": None, "result": None}
    # ---------------- TẦNG 2: Monitor ----------------
    txn_probe = {"amount_vnd": _amount(body), "beneficiary": str(body.get("beneficiary_account") or "")}
    ac = actor_mod.classify(ab, cid, txn_probe, challenge_passed=challenge_passed)
    pre = {"ip": client_ip, "antibot": {"bot_class": ab["bot_class"], "bot_score": ab["bot_score"], "rules": ab["rules"], "note": ab["note"],
                       "evidence": [e for e in ab["evidence"]][:12], "bot_points": ab["bot_points"], "human_points": ab["human_points"]},
           "actor": ac}
    body = dict(body)
    if ac["actor_type"] == "HUMAN":
        body["session_risk"] = ab["bot_score"]                  # điểm bot (0–100) của tầng 1 → đặc trưng session_risk của Monitor
        if ses.get("device_id"):
            body["device_id"] = ses["device_id"]
    res = engine.evaluate(body, (agent or {}).get("agent_id") or "", source=source, customer_hint=cid, ip=ip,
                          use_llm=(ac["actor_type"] == "AGENT"), actor=ac["actor_type"],
                          source_system=source_system if ac["actor_type"] == "HUMAN" else None, pre=pre)
    antibot_txn.persist(req, ab, res.get("action_id"))
    antibot_txn.record_outcome(req, declined=(res["decision"] == "BLOCK"))
    return {"stage": "MONITOR", "antibot": ab, "actor": ac, "result": res}


def antibot_response(ab):
    """Phản hồi chuẩn cho cửa vào khi Anti-Bot dừng giao dịch."""
    out = {"stage": "ANTIBOT", "action": ab["action"], "bot_class": ab["bot_class"], "message": ab["note"], "reason_codes": ab["rules"]}
    if ab["action"] == antibot_txn.CHALLENGE:
        out["challenge"] = {"type": ab["challenge"], "how": "Hiển thị thử thách (Turnstile/xác thực lại) cho khách rồi gửi lại với session.turnstile_ok=true"
                            if ab["declared_actor"] == "HUMAN" else "Khóa Agent cần được chi nhánh/HQ rà soát trước khi dùng tiếp"}
    return out
