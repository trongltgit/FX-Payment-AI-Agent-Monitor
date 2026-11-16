"""
LLM Critic (Groq – API tương thích OpenAI) + bộ phản biện luật (fallback) tiếng Việt.

Nguyên tắc an toàn:
  * LLM CHỈ được nâng mức (ALLOW→KYA→REVIEW). Không bao giờ hạ mức, không bao giờ vượt hard policy.
  * Chỉ gửi dữ liệu đã tối thiểu hóa (không PAN, không tên, không số tài khoản; số tiền làm tròn).
  * Lỗi/timeout -> dùng bộ phản biện luật, hệ thống vẫn quyết định được (fail-safe).
LLM_PROVIDER=groq + GROQ_API_KEY để bật; LLM_MODE=gray (mặc định: chỉ gọi khi vùng xám) | always | off.
"""
import json
import os

import requests

ORDER = {"ALLOW": 0, "KYA": 1, "REVIEW": 2, "BLOCK": 3}


def enabled() -> bool:
    return os.environ.get("LLM_PROVIDER", "mock").lower() == "groq" and bool(os.environ.get("GROQ_API_KEY"))


def status() -> dict:
    return {"provider": "groq" if enabled() else "rule-based (mock)",
            "model": os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile") if enabled() else "-",
            "mode": os.environ.get("LLM_MODE", "gray"),
            "note": "" if enabled() else "Đặt LLM_PROVIDER=groq và GROQ_API_KEY để bật Groq."}


def should_call(final_risk: float, decision: str, triggers) -> bool:
    mode = os.environ.get("LLM_MODE", "gray").lower()
    if mode == "off":
        return False
    if mode == "always":
        return True
    return 0.20 <= final_risk < 0.80 or bool(triggers) or decision in ("KYA", "REVIEW")


def _rule_critic(summary: dict) -> dict:
    risk = summary["final_risk"]
    why = []
    dom = summary["domain"]
    if summary["ratio"] and summary["ratio"] >= 3:
        why.append(f"giá trị gấp {summary['ratio']:.1f} lần thói quen của khách")
        risk = max(risk, 0.55)
    for c in summary["trigger_codes"]:
        why.append({"FIRST_ONLINE": "khách chưa từng giao dịch online/agent", "DORMANT_WAKE": "tài khoản ngủ đông bỗng hoạt động",
                    "NEW_BENEFICIARY": "người nhận mới", "NEW_COUNTRY": "quốc gia mới", "HIGH_RISK_COUNTRY": "quốc gia rủi ro cao",
                    "HIGH_RISK_MCC": "ngành hàng rủi ro cao", "NO_3DS": "thẻ không có 3-D Secure", "BALANCE_DRAIN": "rút gần hết số dư",
                    "CARD_TESTING": "mẫu dò thẻ", "LEVERAGE_SPIKE": "đòn bẩy tăng đột biến", "AGENT_PROBATION": "agent đang thử việc",
                    "AMOUNT_OVER_KYA": "giá trị vượt ngưỡng xác minh"}.get(c, c))
    if "CARD_TESTING" in summary["trigger_codes"] or ("BALANCE_DRAIN" in summary["trigger_codes"] and summary["behavior"] > 0.5):
        risk = max(risk, 0.7)
    rec = "REVIEW" if risk >= 0.65 else ("KYA" if risk >= 0.35 or summary["trigger_codes"] else "ALLOW")
    text = ("Phản biện (luật): " + ("; ".join(why) if why else "hành vi nằm trong khung thông thường của khách hàng")
            + f". Điểm tổng hợp {risk:.2f} → khuyến nghị {rec}.")
    return {"risk": round(risk, 3), "recommendation": rec, "explanation": text, "source": "rule"}


def critique(summary: dict) -> dict:
    base = _rule_critic(summary)
    if not enabled():
        return base
    prompt = (
        "Bạn là chuyên viên kiểm soát rủi ro ngân hàng. Đánh giá giao dịch do AI Agent thực hiện (đã ẩn danh). "
        "Chỉ trả về JSON: {\"risk\":0-1,\"recommendation\":\"ALLOW|KYA|REVIEW\",\"explanation\":\"<=60 từ tiếng Việt\"}. "
        "KYA = yêu cầu khách xác nhận qua ứng dụng Authenticator; REVIEW = chờ nhân viên chi nhánh duyệt.\n"
        + json.dumps(summary, ensure_ascii=False))
    try:
        r = requests.post(
            os.environ.get("LLM_BASE_URL", "https://api.groq.com/openai/v1") + "/chat/completions",
            headers={"Authorization": "Bearer " + os.environ["GROQ_API_KEY"], "Content-Type": "application/json"},
            json={"model": os.environ.get("LLM_MODEL", "llama-3.3-70b-versatile"), "temperature": 0.1,
                  "messages": [{"role": "system", "content": "Chỉ xuất JSON hợp lệ."}, {"role": "user", "content": prompt}]},
            timeout=float(os.environ.get("LLM_TIMEOUT", "6")))
        r.raise_for_status()
        txt = r.json()["choices"][0]["message"]["content"].strip().removeprefix("```json").removesuffix("```").strip()
        d = json.loads(txt)
        rec = str(d.get("recommendation", "")).upper()
        if rec not in ("ALLOW", "KYA", "REVIEW"):
            rec = base["recommendation"]
        return {"risk": round(float(d.get("risk", base["risk"])), 3), "recommendation": rec,
                "explanation": str(d.get("explanation", ""))[:600] or base["explanation"], "source": "groq"}
    except Exception as e:     # noqa: BLE001
        base["explanation"] += f" [Groq lỗi: {type(e).__name__}]"
        return base
