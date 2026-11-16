"""TẦNG 2a – PHÂN LOẠI NGƯỜI THỰC HIỆN tại AI Agent Monitor: AI AGENT hay NGƯỜI?

Dựa trên (1) thông tin xác thực/khai báo, (2) kết luận của Anti-Bot (tầng 1), (3) kiểm tra chéo trong dữ liệu giao dịch.
Kết quả: actor_type ∈ {AGENT, HUMAN}, confidence 0–1, unverified (True → Monitor thêm trigger ACTOR_UNVERIFIED → xác minh bổ sung).

Bảng điều kiện:
  Khóa Agent hợp lệ + Anti-Bot = AUTOMATION_AUTHORIZED            → AGENT, tin cậy 0,95
  Phiên người + HUMAN_VERIFIED                                    → HUMAN, tin cậy 0,95
  Phiên người + HUMAN_LIKELY                                      → HUMAN, tin cậy 0,75 (0,60 nếu có dấu hiệu tự động bị bù trừ)
  Phiên người đã vượt thử thách sau SUSPECT                       → HUMAN, tin cậy 0,60, unverified
  Người khai báo nhưng vừa có giao dịch Agent y hệt (≤ 10 giây)   → unverified (nghi Agent chạy qua kênh người: AGENT_ECHO)
  tin cậy < 0,65                                                  → unverified
"""
from agentmon import db
from utils import store

ECHO_WINDOW_S = 10
UNVERIFIED_BELOW = 0.65


def classify(ab: dict, customer_id: str, txn: dict, challenge_passed: bool = False) -> dict:
    declared = ab["declared_actor"]
    cls = ab["bot_class"]
    reasons = []
    if declared == "AGENT":
        conf = 0.95 if cls == "AUTOMATION_AUTHORIZED" else 0.4
        reasons.append("Khóa Agent hợp lệ; hành vi tự động là bình thường")
        return {"actor_type": "AGENT", "confidence": conf, "unverified": conf < UNVERIFIED_BELOW, "declared": declared,
                "observed": "AUTOMATION", "reasons": reasons}
    if cls == "HUMAN_VERIFIED":
        conf = 0.95
        reasons.append("Bằng chứng người mạnh (Anti-Bot)")
    elif cls == "HUMAN_LIKELY":
        conf = 0.60 if ab.get("observed_automation") else 0.75
        reasons.append("Giống người nhưng " + ("có dấu hiệu tự động được bằng chứng người bù trừ" if ab.get("observed_automation") else "bằng chứng chưa mạnh"))
    elif challenge_passed:
        conf = 0.60
        reasons.append("Đã vượt thử thách sau khi bị nghi ngờ")
    else:
        conf = 0.40
        reasons.append(f"Anti-Bot: {cls}")
    # Kiểm tra chéo dữ liệu: giao dịch "của người" trùng khít giao dịch Agent vừa gửi
    if customer_id and txn:
        now = store.now()
        row = db.one("SELECT id FROM actions WHERE customer_id=? AND COALESCE(actor_type,'AGENT')='AGENT' AND ts>? AND amount_vnd=? AND COALESCE(beneficiary,'')=? AND sim!=2 LIMIT 1",
                     (customer_id, now - ECHO_WINDOW_S, float(txn.get("amount_vnd") or 0), str(txn.get("beneficiary") or "")))
        if row and txn.get("amount_vnd"):
            conf = min(conf, 0.5)
            reasons.append(f"AGENT_ECHO: Agent vừa gửi giao dịch y hệt trong {ECHO_WINDOW_S}s")
    return {"actor_type": "HUMAN", "confidence": round(conf, 2), "unverified": conf < UNVERIFIED_BELOW, "declared": declared,
            "observed": "AUTOMATION" if ab.get("observed_automation") else "INTERACTIVE", "reasons": reasons}
