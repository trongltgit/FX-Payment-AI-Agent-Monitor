"""Ma trận tấn công cấp GIAO DỊCH qua pipeline Anti-Bot → Monitor.   python -m tools.txn_attack_matrix
Chạy trên CSDL tạm; in bảng kết quả (kỳ vọng vs thực tế) và ghi tools/results/txn_attack_matrix.md. Thoát mã 1 nếu có kịch bản lệch kỳ vọng."""
import os
import sys
import tempfile
import time

_tmp = os.path.join(tempfile.mkdtemp(), "ax.db")
os.environ.update(PRICING_ENVIRONMENT="demo", SECRET_KEY="x" * 48, API_SIGNING_SECRET="y" * 48, DEMO_PASSWORD="demo-pass-12345",
                  AGENTMON_DB=_tmp, LLM_PROVIDER="mock", DEPLOY_PROFILE="pilot")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402

create_app()
from agentmon import db, engine, lab, pipeline, registry  # noqa: E402
from services import bot_defense  # noqa: E402
from utils import store  # noqa: E402

GOOD = dict(device_attested=True, device_known=True, mfa_age_s=90, pointer_events=15, key_events=20, think_time_ms=5200)
_i = [0]


def uid(p):
    _i[0] += 1
    return f"{p}{_i[0]}"


def body(cid="CUST001", kind="TRANSFER", **kw):
    u = lab._usual(cid, "PAY")
    b = dict(customer_id=cid, request_id=uid("rq"), domain="PAY", kind=kind, amount_vnd=u["tamt"], beneficiary_account=u["ben"])
    b.update(kw)
    return b


def human(b, ua="bank-core/1.0", ip=None, hs=0, src="DIGIBANK", **k):
    return pipeline.process(credential="SOURCE_KEY", body=b, ip=ip or f"10.1.{_i[0] % 250}.{_i[0] // 250 + 1}", ua=ua, header_score=hs, source_system=src, **k)


def run():
    rows = []

    def case(name, expect_stage, expect_action, pr):
        stage = pr["stage"]
        action = pr["antibot"]["action"] if stage == "ANTIBOT" else pr["result"]["decision"]
        ok = stage == expect_stage and (expect_action is None or action in expect_action.split("|"))
        rows.append((name, f"{expect_stage}/{expect_action or '*'}", f"{stage}/{action}", pr["antibot"]["bot_class"], ",".join(pr["antibot"]["rules"]) or "-", "ĐẠT" if ok else "LỆCH"))

    case("Người thật: thiết bị chứng thực + MFA + telemetry", "MONITOR", None, human(body(session=dict(GOOD, device_id="DEV-IPH001"))))
    case("Script curl, header lạ, xác nhận 50ms", "ANTIBOT", "BLOCK", human(body(session=dict(think_time_ms=50, device_id=uid("d"))), ua="curl/8.4", hs=70))
    case("Nghi bot không khai báo (chỉ xác nhận quá nhanh)", "ANTIBOT", "CHALLENGE", human(body(session=dict(think_time_ms=100, device_id=uid("d")))))
    case("Vượt thử thách sau nghi ngờ → qua tầng 1, Monitor xác thực bổ sung", "MONITOR", "STEP_UP|REVIEW|BLOCK",
         human(body(session=dict(think_time_ms=100, device_id=uid("d"), turnstile_ok=True)), challenge_passed=True))
    n = uid("n")
    human(body(session=dict(GOOD, nonce=n, device_id="DEV-IPH001")))
    case("Replay nonce", "ANTIBOT", "BLOCK", human(body(session=dict(GOOD, nonce=n, device_id="DEV-IPH001"))))
    case("Yêu cầu cũ 1 giờ (dấu thời gian)", "ANTIBOT", "BLOCK", human(body(session=dict(GOOD, ts=time.time() - 3600))))
    ip, dev = "198.51.100.77", uid("dev")
    cards = [lab._card(c) for c in ("CUST001", "CUST002", "CUST003", "CUST005", "CUST004")]
    for k in range(5):
        pr = human(body(kind="ONLINE_PURCHASE", card_token=cards[k], merchant_id="M300", mcc="5411", session=dict(GOOD, device_id=dev, client_ip=ip)),
                   ip="10.0.0.1", src="CARD_SWITCH")
    case("Dò BIN: 5 thẻ khác nhau từ một thiết bị", "ANTIBOT", "BLOCK", pr)
    ip2, dev2 = "198.51.100.78", uid("dev")
    for k in range(6):
        pr = human(body(kind="CARD_PAYMENT", card_token=lab._card("CUST001"), merchant_id=f"MT{k}", mcc="5732", amount_vnd=9_000,
                        session=dict(GOOD, device_id=dev2, client_ip=ip2)), ip="10.0.0.1", src="CARD_SWITCH")
    case("Card testing: 6 giao dịch 9.000đ liên tiếp", "ANTIBOT", "BLOCK", pr)
    dev3 = uid("farm")
    for c in ("CUST001", "CUST002", "CUST003", "CUST005"):
        pr = human(body(cid=c, session=dict(GOOD, device_id=dev3)))
    case("Trang trại tài khoản: 4 khách dùng chung thiết bị", "ANTIBOT", "BLOCK", pr)
    bad_ip = "203.0.113.200"
    bot_defense.ban_ip(bad_ip, "matrix", ttl=120)
    case("IP đang bị cấm", "ANTIBOT", "BLOCK", human(body(session=dict(GOOD, client_ip=bad_ip))))
    ag = registry.get(lab._agent_for("CUST001", "PAY"))
    u = lab._usual("CUST001", "PAY")
    ab_body = dict(domain="PAY", kind="TRANSFER", amount_vnd=u["tamt"], beneficiary_account=u["ben"])
    case("AI Agent hợp lệ (nhịp đều là bình thường)", "MONITOR", None,
         pipeline.process(credential="AGENT_KEY", body=ab_body, ip="192.0.2.10", ua="my-agent/1", agent=ag, source="MATRIX"))
    case("Khóa Agent bị NGƯỜI dùng (chuột/bàn phím)", "ANTIBOT", "CHALLENGE",
         pipeline.process(credential="AGENT_KEY", body=dict(ab_body, session=dict(pointer_events=12, key_events=18)), ip="192.0.2.11", ua="x", agent=ag, source="MATRIX"))
    pipeline.process(credential="AGENT_KEY", body=ab_body, ip="192.0.2.12", ua="agent", agent=ag, source="MATRIX")
    case("Agent chạy qua kênh người (AGENT_ECHO)", "MONITOR", "STEP_UP|REVIEW",
         human(body(amount_vnd=u["tamt"], beneficiary_account=u["ben"], session=dict(GOOD, device_id="DEV-IPH001"))))
    # ---- ATM + camera AI + khuôn mặt (người thật / người khác / giả mạo / không có người / Agent)
    from agentmon import biometrics
    ATM_C = "CUST005"          # khách riêng cho nhóm ATM (tránh điểm nghi ngờ tích lũy từ các kịch bản tấn công phía trước)
    tok = lab._card(ATM_C)
    au = lab._usual(ATM_C, "PAY")
    atm_id = au.get("atm_ref") or "ATM0101"
    me = biometrics.demo_embedding(ATM_C, noise=0.12, noise_seed=5)
    good = dict(face_present=True, faces_in_frame=1, liveness_score=0.97, injection_attack_score=0.02, capture_quality=0.9, camera_status="OK")

    def atm(bio, **kw):
        b = dict(customer_id=ATM_C, request_id=uid("atm"), domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=au.get("atm_amt") or 3_000_000, card_token=tok, atm_id=atm_id, biometric=bio)
        b.update(kw)
        return human(b, src="ATM_SWITCH", ua="atm-switch/1.0")
    case("ATM: chính chủ (liveness + khuôn mặt khớp)", "MONITOR", "ALLOW", atm(dict(good, face_embedding=me)))
    case("ATM: virtual camera / deepfake (injection 0,95)", "ANTIBOT", "BLOCK", atm(dict(good, injection_attack_score=0.95, face_embedding=me)))
    case("ATM: không có người trước máy", "ANTIBOT", "BLOCK", atm(dict(good, face_present=False, faces_in_frame=0)))
    case("ATM: khuôn mặt người khác dùng thẻ", "MONITOR", "BLOCK", atm(dict(good, face_embedding=biometrics.demo_embedding("ke-trom"))))
    case("ATM: khuôn mặt chưa chắc → xác nhận qua điện thoại", "MONITOR", "STEP_UP", atm(dict(good, face_match_score=0.65)))
    ag2 = registry.get(lab._agent_for(ATM_C, "PAY"))
    case("ATM: AI Agent rút tiền mặt từ xa", "MONITOR", "KYA",
         pipeline.process(credential="AGENT_KEY", body=dict(domain="PAY", kind="ATM_WITHDRAWAL", amount_vnd=2_000_000, card_token=tok, atm_id=atm_id), ip="192.0.2.30", ua="agent", agent=ag2, source="MATRIX"))
    return rows


if __name__ == "__main__":
    rows = [r for r in run() if r]
    w = [max(len(str(r[i])) for r in rows + [("Kịch bản", "Kỳ vọng", "Thực tế", "Phân loại", "Luật", "KQ")]) for i in range(6)]
    head = ("Kịch bản", "Kỳ vọng", "Thực tế", "Phân loại", "Luật", "KQ")
    lines = [" | ".join(str(x).ljust(w[i]) for i, x in enumerate(head))] + ["-+-".join("-" * x for x in w)]
    lines += [" | ".join(str(x).ljust(w[i]) for i, x in enumerate(r)) for r in rows]
    print("\n".join(lines))
    os.makedirs(os.path.join(os.path.dirname(__file__), "results"), exist_ok=True)
    with open(os.path.join(os.path.dirname(__file__), "results", "txn_attack_matrix.md"), "w", encoding="utf-8") as fh:
        fh.write("# Ma trận tấn công cấp giao dịch (Anti-Bot → Monitor)\n\n| " + " | ".join(head) + " |\n|" + "---|" * 6 + "\n")
        fh.writelines("| " + " | ".join(str(x) for x in r) + " |\n" for r in rows)
    sys.exit(0 if all(r[-1] == "ĐẠT" for r in rows) else 1)
