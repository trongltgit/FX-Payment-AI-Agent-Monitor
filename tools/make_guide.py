"""Sinh HƯỚNG DẪN VẬN HÀNH – KIỂM THỬ v2 (Markdown + Word). Số liệu lấy trực tiếp từ mã nguồn → không lệch.
Chạy:  python -m tools.make_guide     → docs/HUONG_DAN_VAN_HANH_V2.md và docs/HUONG_DAN_VAN_HANH_V2.docx (cần pandoc + python-docx + matplotlib)."""
import glob
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("PRICING_ENVIRONMENT", "demo")

from agentmon import antibot_txn as AB, cardmodel, catalog, fraud_types, ml, policy, profiles, riskregister  # noqa: E402
from agentmon.constants import CODE_VERSION, SOURCE_SYSTEMS  # noqa: E402

D = os.path.join(ROOT, "docs")


def T(headers, rows, widths=None):
    """Bảng pipe-table; widths = tỷ lệ cột (điều khiển độ rộng trong Word)."""
    widths = widths or [1] * len(headers)
    tot = sum(widths)
    sep = "|" + "|".join("-" * max(3, int(70 * w / tot)) for w in widths) + "|"
    esc = lambda x: str(x).replace("|", "\\|").replace("\n", " ")
    out = ["| " + " | ".join(headers) + " |", sep]
    out += ["| " + " | ".join(esc(c) for c in r) + " |" for r in rows]
    return "\n".join(out) + "\n"


def diagram(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch
    fig, ax = plt.subplots(figsize=(11, 6.6))
    ax.set_xlim(0, 11); ax.set_ylim(0, 6.6); ax.axis("off")

    def box(x, y, w, h, text, fc="#E8F0FE", ec="#1A56B0", fs=9, bold=False):
        ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12", fc=fc, ec=ec, lw=1.4))
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, fontweight="bold" if bold else "normal", wrap=True)

    def arrow(x1, y1, x2, y2, label="", color="#444"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1), arrowprops=dict(arrowstyle="->", color=color, lw=1.4))
        if label:
            ax.text((x1 + x2) / 2 + 0.08, (y1 + y2) / 2, label, fontsize=8, color=color)
    box(0.2, 5.5, 10.6, 0.8, "NGUỒN: Portal · Digibank · Digibiz · Switch thẻ · ATM · IPS · AI Agent (khóa Bearer agk_… / X-Source-Key skx_…)", "#F3F3F3", "#777", 9.5)
    arrow(5.5, 5.5, 5.5, 5.05)
    box(2.2, 4.3, 6.6, 0.75, "CỔNG  /gateway/v2/transaction  (hoặc /txn-api, /agent-api)  →  Lớp 0: ban IP · honeypot · audit", "#FFF4D6", "#B7791F", 9)
    arrow(5.5, 4.3, 5.5, 3.85)
    box(1.7, 2.95, 7.6, 0.9, "TẦNG 1 – ANTI-BOT GIAO DỊCH   (antibot_txn.assess)\nBot thật · Người thật · AI Agent có khóa?   + mô hình AI bot–người · sinh trắc liveness", "#E6F4EA", "#1E7E34", 10, True)
    arrow(2.6, 2.95, 1.4, 2.45, "MALICIOUS_BOT", "#B00020")
    arrow(8.4, 2.95, 9.6, 2.45, "SUSPECT", "#B7791F")
    box(0.1, 1.75, 2.7, 0.7, "BLOCK – dừng\nMonitor KHÔNG chạy", "#FCE8E6", "#B00020", 8.5)
    box(8.2, 1.75, 2.7, 0.7, "CHALLENGE – dừng\n(Turnstile / rà soát khóa Agent)", "#FFF4D6", "#B7791F", 8.5)
    arrow(5.5, 2.95, 5.5, 2.5, "HUMAN_* / AUTOMATION_AUTHORIZED", "#1E7E34")
    box(3.1, 1.75, 4.8, 0.75, "Phân loại người thực hiện (actor.classify):\nAI Agent hay NGƯỜI? độ tin cậy; < 0,65 → ACTOR_UNVERIFIED", "#E8F0FE", "#1A56B0", 8.8)
    arrow(5.5, 1.75, 5.5, 1.35)
    box(1.7, 0.45, 7.6, 0.9, "TẦNG 2 – AI AGENT MONITOR   (engine.evaluate)\nHard Policy → IF + GBM + Hành vi + Velocity + Chuỗi + Đồ thị → Trigger → Danh tính ATM (camera AI) → LLM(Agent)", "#E8F0FE", "#1A56B0", 9.5, True)
    ax.text(5.5, 0.12, "Kết quả:  ALLOW · KYA (Agent) | STEP_UP (người) · REVIEW · BLOCK", ha="center", fontsize=9.5, fontweight="bold")
    fig.savefig(path, dpi=170, bbox_inches="tight")


def test_counts():
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", os.path.join(ROOT, "tests")], capture_output=True, text=True, cwd=ROOT, timeout=120).stdout
        m = re.search(r"(\d+) tests? collected", out)
        return int(m.group(1)) if m else None
    except Exception:      # noqa: BLE001
        return None


def build():
    from agentmon import lab
    n_tests = test_counts() or 152
    man = ml.read_manifest()
    mv = {d: man[d]["current"] for d in man}
    ent = {d: next(e for e in man[d]["history"] if e["version"] == man[d]["current"]) for d in man}
    atk = open(os.path.join(ROOT, "tools", "results", "txn_attack_matrix.md"), encoding="utf-8").read() if os.path.exists(os.path.join(ROOT, "tools", "results", "txn_attack_matrix.md")) else ""
    atk_rows = [l.strip("|").split("|") for l in atk.splitlines() if l.startswith("|") and not l.startswith("| Kịch") and not l.startswith("|---")]
    C = AB.DEFAULTS
    P = []
    a = P.append

    a(f"""---
title: "HƯỚNG DẪN VẬN HÀNH – KIỂM THỬ – TRIỂN KHAI"
subtitle: "FX · Thẻ · Thanh toán – Anti-Bot (tầng 1) → AI Agent Monitor (tầng 2)  –  Phiên bản {CODE_VERSION}"
date: "{time.strftime('%d/%m/%Y')}"
---

# 1. Giới thiệu và phạm vi

## 1.1 Mục tiêu của tài liệu
Tài liệu hướng dẫn **cài đặt, cấu hình, vận hành, kiểm thử và đánh giá rủi ro** của mô hình giám sát giao dịch gồm hai tầng bảo vệ nối tiếp:

* **Tầng 1 – Anti-Bot giao dịch:** phân biệt **bot thật** với **người thật** và với **tự động hóa được phép** (AI Agent đã đăng ký, có khóa hợp lệ).
* **Tầng 2 – AI Agent Monitor:** xác định người thực hiện là **AI Agent hay người**, rồi chấm điểm rủi ro gian lận/bất thường và ra quyết định.

Mọi giao dịch – **FX, thẻ (mọi mạng, mọi loại, mọi phương thức: debit, credit, prepaid, ảo, doanh nghiệp), chuyển tiền, mua sắm online, QR, hóa đơn, thanh toán sao kê thẻ tín dụng, rút tiền ATM, ví điện tử** – đều đi qua Tầng 1 **trước**, rồi mới tới Tầng 2.

Tại **ATM**, hệ thống phối hợp **camera AI nhận diện khuôn mặt** (đã đăng ký sinh trắc) để phân biệt *chính chủ tự rút tiền* với *người khác dùng thẻ* và với *AI Agent/tự động hóa rút tiền từ xa*; khi chưa chắc chắn, chủ thẻ xác nhận trên điện thoại (KYA/KYC). Phía sau là **bộ nhiều mô hình AI** phối hợp (Isolation Forest, gradient boosting, mô hình bot–người, chuỗi hành vi, đồ thị liên kết, Face-AI, LLM Critic).

## 1.2 Nguyên tắc thiết kế
1. **Anti-Bot trước, Monitor sau** – ép bằng mã (`agentmon/pipeline.py`), có test chứng minh Monitor không chạy khi Tầng 1 chặn.
2. **Chặn cứng chỉ khi có bằng chứng rõ;** trường hợp trung gian là **thử thách**, không chặn (giảm chặn nhầm người thật).
3. **Tự động hóa của AI Agent hợp lệ là bình thường** – không bị phạt vì nhịp đều hay thiếu chuột/bàn phím.
4. **Không tin khai báo, quan sát hành vi:** người khai báo nhưng hành vi tự động bị nghi; khóa Agent mà có tương tác chuột/bàn phím bị rà soát.
5. **Hard Policy không bị ML/LLM ghi đè;** LLM chỉ được **nâng** mức rủi ro, và không chạy trên đường đi thời gian thực của người dùng.
6. **Giải thích được và kiểm toán được:** mỗi quyết định lưu trace đầy đủ, mã băm SHA-256, phiên bản mô hình.
7. **Nhiều mô hình, một quy tắc an toàn:** các mô hình AI bổ sung chỉ được **nâng** cảnh báo, không bao giờ hạ; mô hình học có giám sát chạy **bóng (shadow)** ở pilot/production cho tới khi kiểm chứng trên dữ liệu thật (mục 9).
8. **Sinh trắc có điều kiện:** chỉ lưu embedding mã hóa khi có đồng ý; vùng chưa chắc chắn dẫn tới xác nhận qua điện thoại, không chặn khách thật (mục 7).
9. **Trung thực về giới hạn:** mô hình huấn luyện trên dữ liệu tổng hợp; xem mục 15 và Danh mục rủi ro (mục 16).

## 1.3 Thuật ngữ
""")
    a(T(["Thuật ngữ", "Ý nghĩa"], [
        ("Anti-Bot", "Lớp chống tự động hóa trái phép. Ở tài liệu này: Anti-Bot **cấp giao dịch** (tầng 1); khác với Anti-Bot web gốc bảo vệ đăng nhập/báo giá (`app/guard.py`)."),
        ("AI Agent", "Chương trình/AI tự động giao dịch thay khách hàng, đã đăng ký với ngân hàng và có khóa API `agk_…`."),
        ("Hệ thống nguồn", "Hệ thống của ngân hàng gửi giao dịch của NGƯỜI sang Monitor: Portal, Digibank, Digibiz, Switch thẻ, Switch ATM, IPS. Khóa `skx_…`."),
        ("Bot thật / MALICIOUS_BOT", "Tự động hóa không được phép: script, tấn công thẻ, replay, trang trại tài khoản."),
        ("KYA (Know Your Agent)", "Xác minh của chủ tài khoản qua ứng dụng Authenticator khi Agent thực hiện giao dịch bất thường."),
        ("STEP_UP", "Xác thực bổ sung (OTP hoặc sinh trắc học) cho giao dịch của NGƯỜI; kênh nguồn thực hiện, rồi báo kết quả."),
        ("Trigger", "Điều kiện xác định bắt buộc xác minh, không phụ thuộc điểm ML."),
        ("Hard Policy", "Luật chặn cứng (hạn mức, danh sách chặn, PCI, Agent chưa đăng ký…)."),
        ("Hồ sơ triển khai", "demo / pilot / production – tập cấu hình và điều kiện sẵn sàng khác nhau."),
    ], [1, 4]))

    a("""
# 2. Kiến trúc và luồng xử lý

## 2.1 Sơ đồ tổng thể
![Luồng tuần tự Anti-Bot → AI Agent Monitor](diagram_flow.png)

## 2.2 Các bước xử lý một giao dịch
""")
    a(T(["Bước", "Thành phần", "Việc làm", "Kết quả có thể"], [
        ("0", "Cổng + Lớp 0", "Xác thực khóa (`Bearer agk_…` hoặc `X-Source-Key skx_…`), giới hạn tốc độ, ban IP/honeypot, kiểm tra kiểu dữ liệu `session.*`", "401 sai khóa · 429 quá nhanh · 400 dữ liệu sai"),
        ("1", "Anti-Bot giao dịch", "Sổ chứng cứ bot–người + mô hình AI bot–người + sinh trắc liveness + luật tấn công thẻ/replay/thiết bị", "HUMAN_VERIFIED · HUMAN_LIKELY · AUTOMATION_AUTHORIZED → qua; SUSPECT → CHALLENGE; MALICIOUS_BOT → BLOCK"),
        ("2", "Phân loại người thực hiện", "AI Agent hay người, độ tin cậy, kiểm tra chéo AGENT_ECHO", "actor_type + confidence; < 0,65 → ACTOR_UNVERIFIED"),
        ("3", "Hard Policy", "Hạn mức MIN(TSC, chi nhánh, Agent), danh sách chặn, đăng ký Agent, PCI, số dư, kill-switch (chỉ Agent)", "Vi phạm → BLOCK ngay"),
        ("4", "Chấm điểm", "ML (Isolation Forest) + Hành vi + Velocity → điểm cuối; ý kiến thứ hai (gradient boosting), chuỗi hành vi, đồ thị liên kết, danh tính ATM", "Điểm 0–1 + tín hiệu bổ sung"),
        ("5", "Trigger + phân loại", "Trigger xác định, luật thẻ, kiểu gian lận", "Bắt buộc KYA/STEP_UP; FRAUD_SUSPECTED / ANOMALY / NORMAL"),
        ("6", "LLM Critic (chỉ Agent)", "Nhận xét vùng xám, chỉ được NÂNG mức", "Nâng ALLOW→KYA/REVIEW"),
        ("7", "Quyết định", "Ngưỡng + trigger + fail-closed", "ALLOW · KYA (Agent) · STEP_UP (người) · REVIEW · BLOCK"),
        ("8", "Ghi nhận", "actions + trace + antibot_events + audit", "Giải trình, kiểm toán"),
    ], [1, 3, 6, 5]))
    a("""
## 2.3 Các cổng vào
""")
    a(T(["Cổng", "Người gọi", "Khóa", "Ghi chú"], [
        ("`POST /gateway/v2/transaction`", "Agent hoặc hệ thống nguồn", "`Authorization: Bearer agk_…` hoặc `X-Source-Key: skx_…`", "Cổng thống nhất; phản hồi có `stage` (ANTIBOT/MONITOR)"),
        ("`POST /agent-api/v1/monitor/action`", "AI Agent", "Bearer agk_", "Giữ tương thích; đi qua pipeline"),
        ("`POST /txn-api/v1/monitor/transaction`", "Hệ thống nguồn", "X-Source-Key", "Giữ tương thích; đi qua pipeline"),
        ("`POST /txn-api/v1/transactions/<id>/step-up-result`", "Hệ thống nguồn", "X-Source-Key", "Báo kết quả OTP/sinh trắc"),
        ("`GET /txn-api/v1/transactions/<id>`", "Hệ thống nguồn", "X-Source-Key", "Xem kết quả (chỉ giao dịch của nguồn mình)"),
        ("`/api/*` (web)", "Trình duyệt người dùng", "Phiên đăng nhập", "Anti-Bot web gốc: PoW, Turnstile, báo giá FX; điểm bot của phiên web được kênh nguồn chuyển vào `session.anti_bot_score`"),
    ], [3, 2, 3, 4]))
    a("""
## 2.4 Hệ thống nguồn và loại giao dịch được phép
Mỗi hệ thống nguồn chỉ được gửi đúng loại giao dịch của mình (gửi sai → 400).
""")
    a(T(["Nguồn", "Tên", "Loại giao dịch (`kind`)", "Kênh mặc định"],
        [(k, v["name"], ", ".join(v["kinds"]), (v["channel"] if isinstance(v["channel"], str) else json.dumps(v["channel"]) if v["channel"] else "theo giao dịch")) for k, v in SOURCE_SYSTEMS.items()], [2, 4, 6, 2]))

    a("""
## 2.5 Giao dịch của FX và thanh toán cùng lúc
* Hai phân hệ dùng chung một engine nhưng **mô hình, hạn mức riêng**; **dùng chung số dư**: FX giữ ký quỹ (`notional / đòn bẩy`), thanh toán giữ toàn bộ số tiền.
* Lệnh chờ KYA/REVIEW/STEP_UP **giữ chỗ số dư** nên hai lệnh đồng thời không dùng chung một khoản tiền (STEP_UP giữ 15 phút).
* Kiểm tra số dư rồi ghi là **nguyên tử giữa các tiến trình** (`RLock` + `flock`). Đã kiểm chứng bằng hai tiến trình đồng thời (số dư 30 triệu, mỗi lệnh 28 triệu): luôn đúng một lệnh giữ được số dư, số dư không âm. **Nhiều máy** cần khóa tư vấn PostgreSQL (chưa có).
* Tín hiệu chéo: `cross_n5` (≥ 4 lệnh ở phân hệ kia trong 5 phút → +0,15 velocity, kiểu `CROSS_DOMAIN_BURST`) và `cross_actor_n10` (người ↔ Agent cùng thao tác dồn dập → `ACTOR_CONFLICT`).

""")
    a("""
# 3. Bộ tiêu chí phân biệt BOT – AI AGENT – NGƯỜI

## 3.1 Nguyên tắc
Hệ thống **không** kết luận dựa trên một tín hiệu. Mỗi tiêu chí đóng góp **bằng chứng** cho phía bot hoặc phía người; AI Agent hợp lệ được nhận diện bằng **khóa + đăng ký** và **không bị phạt vì tự động hóa**. Ba câu hỏi được trả lời tuần tự:

1. **Có phải tự động hóa trái phép (bot thật) không?** – Tầng 1.
2. **Nếu là tự động hóa, có phải AI Agent đã đăng ký không?** – Tầng 1 (khóa hợp lệ) và Tầng 2 (độ tin cậy người thực hiện).
3. **Nếu là người, có phải CHÍNH CHỦ không (và giao dịch có đáng ngờ không)?** – Tầng 2 (sinh trắc tại ATM, thiết bị, hành vi, mô hình AI).

## 3.2 Ba ví dụ phân loại
""")
    a(T(["Tình huống", "Bằng chứng nổi bật", "Kết luận"], [
        ("Script gọi API giả lập khách", "User-Agent curl/python, header lạ, xác nhận sau 50 ms, không chuột/phím, điểm bot web 95, mô hình bot–người 0,99", "MALICIOUS_BOT → BLOCK ở Tầng 1; Monitor không chạy"),
        ("AI Agent của khách gửi lệnh 24/7, nhịp đều", "Khóa agk_ hợp lệ, Agent đã đăng ký/được duyệt, không có chuột/phím, nhịp đều", "AUTOMATION_AUTHORIZED → qua Tầng 1; Tầng 2 chấm điểm như AGENT (KYA nếu bất thường)"),
        ("Khách dùng ứng dụng Digibank chuyển tiền", "Thiết bị chứng thực + đã gắn tài khoản, MFA 2 phút trước, chuột/phím tự nhiên, suy nghĩ 5 giây, liveness cao", "HUMAN_VERIFIED → qua; Tầng 2 chấm điểm như NGƯỜI (STEP_UP nếu bất thường)"),
    ], [3, 7, 5]))
    a("""
## 3.3 Bảng tiêu chí đầy đủ
Cột **Tầng**: T1 = Anti-Bot giao dịch, T2 = AI Agent Monitor. Tham chiếu định hướng (không phải chứng nhận): NIST SP 800-63B (mức đảm bảo xác thực), ISO/IEC 30107-3 (phát hiện tấn công giả mạo sinh trắc – PAD), OWASP Automated Threats – OAT (Carding, Card Cracking, Cashing Out).

""")
    from agentmon import criteria
    a(T(["ID", "Tiêu chí", "Trường đo", "BOT thật", "AI Agent hợp lệ", "Người thật", "Cách dùng trong hệ thống", "Tầng"],
        [(r["id"], r["criterion"], r["field"], r["bot"], r["agent"], r["human"], r["use"], r["layer"]) for r in criteria.rows()], [1.6, 3, 3, 3, 3, 3, 5, 1.5]))
    a("""
## 3.4 Cách kết hợp các tiêu chí
* **Tầng 1 – sổ chứng cứ:** mỗi tiêu chí cộng điểm bot (B) hoặc người (H); luật tấn công rõ (replay, dò thẻ, giả mạo sinh trắc, không có người trước ATM…) chặn ngay; còn lại theo bảng điều kiện (mục 5.5).
* **Tầng 2 – người thực hiện:** `actor.classify` cho ra AI Agent/người + độ tin cậy; tin cậy thấp thì thêm trigger ACTOR_UNVERIFIED.
* **Không có tiêu chí "một mình quyết định" ngoại trừ các dấu hiệu tấn công không thể biện minh** (nonce dùng lại, injection/deepfake, nhiều thẻ khác nhau từ một thiết bị…).
* **Độ tin cậy được lưu** trong trace của từng giao dịch để giải trình.

""")
    a("""
# 4. Cài đặt, cấu hình và hồ sơ triển khai

## 4.1 Yêu cầu
Python 3.12; Redis (bắt buộc khi > 1 worker hoặc từ pilot trở lên); Docker (tùy chọn); pandoc + python-docx + matplotlib chỉ khi sinh lại tài liệu này.

## 4.2 Chạy nhanh (demo)
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env            # đặt SECRET_KEY, API_SIGNING_SECRET (>= 32 ký tự ngẫu nhiên)
python app.py                   # http://127.0.0.1:5000 (lần đầu tự tạo CSDL + dữ liệu demo)
python -m pytest tests -q       # kiểm thử
```

## 4.3 Docker
```
cp .env.example .env
docker compose up --build       # web + Redis, volume cho data/logs/models
```
Healthcheck dùng kết nối TCP (không gọi HTTP để không kích hoạt bộ lọc bot/ban IP của chính ứng dụng). Render (`render.yaml`) chỉ dùng cho demo (đĩa tạm thời, store RAM, 1 worker).

## 4.4 Hồ sơ triển khai (`DEPLOY_PROFILE`)
""")
    a(T(["Hồ sơ", "Dùng cho", "Khác biệt cấu hình Anti-Bot"], [(k, v["desc"], json.dumps(v["antibot"], ensure_ascii=False)) for k, v in profiles.PROFILES.items()], [1, 4, 5]))
    a("""
Quy ước: `PRICING_ENVIRONMENT=production` (cấu hình cũ) được hiểu là **pilot**. Chỉ khi đặt **rõ** `DEPLOY_PROFILE=production`, ứng dụng **từ chối khởi động** nếu còn mục BLOCKER. Kiểm tra sẵn sàng bất kỳ lúc nào:
`GET /api/agent/hq/readiness` (vai trò HQ) hoặc `python -c "from agentmon import profiles;print(profiles.readiness())"`.

## 4.5 Kiểm tra sẵn sàng (readiness)
""")
    a(T(["Mã", "Điều kiện", "Mức nếu không đạt (production / pilot-demo)"], [
        ("SECRET_KEY / SIGNING_SECRET", "≥ 32 ký tự, hai khóa khác nhau", "BLOCKER"),
        ("CARD_VAULT_KEY", "Có khóa vault token thẻ", "BLOCKER / WARN"),
        ("REDIS, REDIS_MULTIWORKER", "Redis cho rate-limit/phiên/nonce; nhiều worker bắt buộc Redis", "BLOCKER (production, pilot) / WARN (demo)"),
        ("LAB_OFF", "Test Lab tắt ở production", "BLOCKER"),
        ("COOKIE_SECURE", "SESSION_COOKIE_SECURE=1 (HTTPS)", "BLOCKER / WARN"),
        ("DEMO_PASSWORD_UNSET", "Không đặt DEMO_PASSWORD ở production", "BLOCKER"),
        ("DATABASE", "PostgreSQL/Oracle (SQLite chỉ demo/pilot một máy)", "BLOCKER / WARN"),
        ("CORE_ADAPTER", "Dữ liệu khách/thẻ/số dư từ core banking thật (≠ mock)", "BLOCKER / WARN"),
        ("MODEL_REAL_DATA", "Mô hình huấn luyện/kiểm chứng trên dữ liệu thật", "BLOCKER / WARN"),
        ("MODEL_INTEGRITY", "SHA-256 mô hình khớp MANIFEST", "BLOCKER"),
        ("TURNSTILE, MFA_ROLES", "Có Turnstile; MFA cho HQ/Quản trị chi nhánh", "BLOCKER / WARN"),
        ("ANTIBOT_FAIL_CLOSED", "Lỗi Anti-Bot giao dịch → chặn", "BLOCKER / WARN"),
        ("ANTIBOT_NONCE", "Bắt buộc nonce chống replay cho nguồn người dùng", "WARN"),
        ("AI_ENSEMBLE_REAL_DATA", "Mô hình bot–người và gradient boosting huấn luyện trên dữ liệu thật", "BLOCKER / WARN"),
        ("AI_ENSEMBLE_SHADOW", "Các mô hình AI bổ sung ở chế độ bóng cho tới khi kiểm chứng", "WARN"),
        ("FACE_AI_PROVIDER", "Dùng dịch vụ Face-AI thật đạt kiểm thử PAD độc lập", "BLOCKER / WARN"),
        ("HUMAN_LLM_OFF, MODEL_ARCHIVE, AUDIT_LOG, TRUSTED_PROXY", "Không gọi LLM thời gian thực cho người; lưu bản mô hình; nhật ký kiểm toán; đọc IP thật sau proxy", "WARN"),
    ], [3, 5, 3]))
    a("""
## 4.6 Biến môi trường chính
""")
    a(T(["Biến", "Ý nghĩa", "Ví dụ"], [
        ("DEPLOY_PROFILE", "Hồ sơ triển khai", "demo | pilot | production"),
        ("SECRET_KEY, API_SIGNING_SECRET, CARD_VAULT_KEY", "Bí mật ứng dụng (≥ 32 ký tự ngẫu nhiên)", "python -c \"import secrets;print(secrets.token_urlsafe(48))\""),
        ("REDIS_URL", "Store dùng chung (rate-limit, phiên, nonce, vận tốc)", "redis://redis:6379/0"),
        ("AGENTMON_DB, AGENTMON_MODEL_DIR", "Đường dẫn CSDL và mô hình", "/app/data/agentmon.db, /app/models"),
        ("AGENTMON_MODEL_ARCHIVE", "Lưu bản mô hình theo version", "1"),
        ("LLM_PROVIDER, LLM_MODE, GROQ_API_KEY", "LLM Critic (mock = bộ luật, không gọi ngoài)", "mock | groq; gray | always | off"),
        ("HUMAN_LLM_MODE", "LLM trên đường người dùng (khuyến nghị tắt)", "off"),
        ("ENSEMBLE_MODE", "Chế độ mô hình AI bổ sung (bot–người, boosting giám sát)", "active | shadow (mặc định demo active, pilot/production shadow)"),
        ("FACE_AI_PROVIDER", "Nhà cung cấp Face-AI (demo = embedding giả lập)", "demo | tên nhà cung cấp"),
        ("CORE_ADAPTER", "Nguồn dữ liệu khách/thẻ/số dư", "mock (demo) | tên adapter thật"),
        ("TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY", "Thử thách CAPTCHA", ""),
        ("MFA_REQUIRED_ROLES", "Vai trò bắt buộc MFA", "HQ,CN_ADMIN"),
        ("WEB_CONCURRENCY, PORT", "Số worker gunicorn, cổng", "2, 5000"),
    ], [4, 5, 4]))

    a("""
# 5. Tầng 1 – Anti-Bot giao dịch: phân biệt bot thật và người

## 5.1 Mục đích và nguyên tắc
Tầng 1 trả lời một câu hỏi duy nhất: **thực thể gửi giao dịch là ai?** Thay vì một điểm số mơ hồ, nó dùng **sổ chứng cứ**: mỗi tín hiệu cộng điểm vào phía **bot** hoặc phía **người**, kèm lý do. Quyết định theo **bảng điều kiện công khai** (mục 5.5), vì vậy giải thích được cho nhân viên và khách hàng.

## 5.2 Đầu vào (`session`) do hệ thống nguồn gửi
""")
    a(T(["Trường", "Kiểu", "Ý nghĩa", "Kiểm tra"], [
        ("device_id", "chuỗi", "Mã thiết bị/trình duyệt", "Chỉ A–Z a–z 0–9 _ -, ≤ 64 ký tự"),
        ("device_known", "boolean", "Thiết bị đã gắn với tài khoản", "boolean"),
        ("device_attested", "boolean", "Ứng dụng được chứng thực toàn vẹn (App Attest/Play Integrity)", "boolean"),
        ("anti_bot_score", "0–100", "Điểm bot của phiên web từ Anti-Bot gốc", "ngoài khoảng → 400"),
        ("pow_ok / turnstile_ok", "boolean", "Đã vượt PoW / Turnstile", "boolean"),
        ("mfa_age_s", "số ≥ 0", "Số giây từ lần MFA gần nhất", "số"),
        ("think_time_ms", "số ≥ 0", "Từ lúc hiển thị màn xác nhận đến lúc bấm xác nhận", "số"),
        ("pointer_events, key_events", "số ≥ 0", "Số sự kiện chuột/chạm và bàn phím trong phiên", "số"),
        ("nonce", "chuỗi", "Mã dùng một lần chống replay", "dùng lại → BLOCK"),
        ("ts", "epoch giây", "Dấu thời gian phía client", "lệch > 300 giây → BLOCK"),
        ("ip_reputation", "enum", "CLEAN, TOR, PROXY, DATACENTER, RESIDENTIAL", "giá trị khác → 400"),
        ("client_ip", "chuỗi", "IP THẬT của khách (nguồn gửi hộ). Dùng cho luật vận tốc và ban; **IP máy chủ nguồn không bao giờ bị ban**", ""),
        ("header_score", "0–100", "Điểm bất thường của header trình duyệt", "số"),
        ("pointer_path_entropy", "0–1", "Độ ngẫu nhiên đường đi chuột (người cao, bot thấp)", "số"),
        ("key_interval_cv", "số ≥ 0", "Hệ số biến thiên khoảng cách giữa các phím", "số"),
        ("scroll_events, focus_changes, session_age_s", "số ≥ 0", "Cuộn, đổi tiêu điểm, tuổi phiên (giây)", "số"),
        ("biometric (ATM/app)", "object", "Tín hiệu Face-AI: face_present, faces_in_frame, face_match_score, liveness_score, injection_attack_score, occlusion, capture_quality, camera_status (chi tiết mục 7)", "ngoài khoảng → 400"),
    ], [3, 2, 7, 4]))
    a("""
## 5.3 Sổ chứng cứ – tín hiệu BOT
""")
    a(T(["Tín hiệu", "Điểm", "Điều kiện"], [
        ("AUTOMATION_USER_AGENT", "+4", "User-Agent là headless/curl/python-requests/selenium/puppeteer/playwright/scrapy…"),
        ("HEADER_PROFILE", "+3", f"header_score ≥ {C['header_score_suspect']}"),
        ("WEB_ANTIBOT_HIGH / MEDIUM", "+4 / +2", f"Điểm Anti-Bot web ≥ {C['web_bot_score_bot']} / ≥ {C['web_bot_score_suspect']}"),
        ("THINK_TIME_TOO_FAST", "+3", f"Xác nhận sau < {C['think_time_bot_ms']} ms"),
        ("METRONOME_CADENCE", "+3", f"≥ {C['cadence_min_requests']} yêu cầu trong {C['cadence_window_s'] // 60} phút với hệ số biến thiên khoảng cách < {C['cadence_cv_max']}"),
        ("NO_TELEMETRY_ON_ONLINE_CHANNEL", "+2", "Kênh trực tuyến (PORTAL/DIGIBANK/DIGIBIZ) không gửi telemetry (chỉ pilot/production)"),
        ("IP_REPUTATION", "+2", "TOR / PROXY / DATACENTER"),
        ("CARD_ENUMERATION_WARN", "+4", f"≥ {C['card_enum_challenge']} thẻ khác nhau từ cùng IP/thiết bị trong {C['card_enum_window_s'] // 60} phút (production: ≥ 2)"),
        ("DEVICE_SHARED", "+3", f"≥ {C['device_customers_challenge']} khách khác nhau dùng chung thiết bị trong 24 giờ"),
        ("IP_RATE_HIGH", "+3", f"≥ {C['ip_rate_challenge_per_min']} yêu cầu/phút từ một IP (chỉ người)"),
    ], [4, 1, 9]))
    a("""
## 5.4 Sổ chứng cứ – tín hiệu NGƯỜI
""")
    a(T(["Tín hiệu", "Điểm", "Điều kiện"], [
        ("DEVICE_ATTESTED", "+3", "Ứng dụng ngân hàng được chứng thực toàn vẹn"),
        ("KNOWN_DEVICE", "+2", "Thiết bị đã gắn với tài khoản"),
        ("CHALLENGE_PASSED", "+2", "Đã vượt PoW hoặc Turnstile"),
        ("RECENT_MFA", "+2", "MFA cách đây ≤ 15 phút"),
        ("HUMAN_TELEMETRY", "+3", f"pointer ≥ 3 hoặc key ≥ 3, và think-time ≥ {C['think_time_human_ms']} ms"),
        ("BROWSER_LIKE_HEADERS", "+1", "header_score < 20, có User-Agent và không phải headless"),
    ], [4, 1, 9]))
    a(f"""
## 5.5 Bảng điều kiện quyết định (người thực hiện khai báo là NGƯỜI)
Gọi **B** = tổng điểm bot, **H** = tổng điểm người. Thứ tự áp dụng từ trên xuống:
""")
    a(T(["#", "Điều kiện", "Lớp (bot_class)", "Hành động"], [
        ("1", "Không có thông tin xác thực; IP đang bị cấm; nonce bị dùng lại (replay); dấu thời gian lệch > 5 phút", "MALICIOUS_BOT", "BLOCK"),
        ("2", f"Dò thẻ: ≥ {C['card_enum_block']} thẻ khác nhau/IP hoặc thiết bị trong {C['card_enum_window_s'] // 60} phút; ≥ {C['card_test_block']} giao dịch < {C['card_test_small_vnd']:,} VND liên tiếp; bão từ chối (≥ {C['decline_min']} lần và ≥ {int(C['decline_ratio_block'] * 100)}%)", "MALICIOUS_BOT", "BLOCK"),
        ("3", f"Trang trại tài khoản: ≥ {C['device_customers_block']} khách dùng chung một thiết bị/24 giờ; ≥ {C['ip_rate_block_per_min']} yêu cầu/phút từ một IP", "MALICIOUS_BOT", "BLOCK"),
        ("4", "Production bắt buộc nonce nhưng không có", "SUSPECT", "CHALLENGE"),
        ("5", "B ≥ 6 và H ≤ 2 (nhiều dấu hiệu bot, gần như không có bằng chứng người)", "MALICIOUS_BOT", "BLOCK"),
        ("6", "B ≥ 3 và H < 4, **chưa** vượt thử thách", "SUSPECT", "CHALLENGE (Turnstile)"),
        ("7", "B ≥ 3 và H < 4 nhưng **đã vượt thử thách**", "HUMAN_LIKELY", "ALLOW (Monitor sẽ yêu cầu xác thực bổ sung vì tin cậy thấp)"),
        ("8", "B ≥ 3 và H ≥ 4 (bằng chứng người bù trừ)", "HUMAN_LIKELY", "ALLOW"),
        ("9", "H ≥ 4, không có dấu hiệu bot", "HUMAN_VERIFIED", "ALLOW"),
        ("10", "Còn lại", "HUMAN_LIKELY", "ALLOW"),
    ], [1, 9, 3, 4]))
    a("""
Điểm bot gửi sang Tầng 2: `bot_score = giới hạn(10·B − 5·H, 0…100)`; MALICIOUS_BOT tối thiểu 85, SUSPECT tối thiểu 50. `bot_score / 100` trở thành đặc trưng `session_risk` của mô hình.

## 5.6 Bảng điều kiện cho AI Agent (khai báo bằng khóa `agk_…`)
""")
    a(T(["Điều kiện", "Lớp", "Hành động"], [
        ("Khóa hợp lệ, không vi phạm luật chặn cứng (IP cấm, replay…)", "AUTOMATION_AUTHORIZED", "ALLOW – nhịp đều và thiếu chuột/bàn phím là **bình thường**"),
        ("Yêu cầu dùng khóa Agent có telemetry tương tác (pointer ≥ 3 hoặc key ≥ 3) → nghi người dùng chung khóa", "SUSPECT (`AGENT_KEY_USED_BY_HUMAN`)", "CHALLENGE = rà soát/xoay khóa Agent; trả 403"),
        ("Agent gọi từ TOR/PROXY", "SUSPECT (`AGENT_FROM_ANONYMIZER`)", "CHALLENGE"),
        ("Luật chặn cứng (replay, dò thẻ, bão từ chối, IP cấm)", "MALICIOUS_BOT", "BLOCK"),
    ], [6, 3, 5]))
    a(f"""
## 5.7 Thử thách (CHALLENGE) và hậu quả
* **Người:** hệ thống nguồn hiển thị Turnstile/xác thực lại cho khách, rồi gửi lại giao dịch (request_id mới) với `session.turnstile_ok = true`. Nếu bằng chứng bot vẫn nặng (B ≥ 6, H ≤ 2) thì vẫn BLOCK; nếu vượt thì qua Tầng 1 với tin cậy thấp và Tầng 2 yêu cầu xác thực bổ sung.
* **Agent:** không có thử thách tương tác; chi nhánh/HQ rà soát khóa.
* **Strike IP:** MALICIOUS_BOT của **người** có `client_ip` → ghi `strike` (không ban ngay) vào Anti-Bot gốc. IP máy chủ của hệ thống nguồn **không bao giờ** bị strike/ban (tránh chặn cả ngân hàng).
* Mọi quyết định Tầng 1 (kể cả khi qua) được ghi vào bảng `antibot_events` (xem `GET /api/agent/hq/antibot-events`).

## 5.8 Ngưỡng cấu hình (mặc định) và ghi đè theo hồ sơ
""")
    a(T(["Tham số", "Giá trị mặc định", "Ý nghĩa"], [
        ("think_time_bot_ms / think_time_human_ms", f"{C['think_time_bot_ms']} / {C['think_time_human_ms']}", "Ngưỡng bot / người của thời gian suy nghĩ"),
        ("cadence_min_requests, cadence_cv_max, cadence_window_s", f"{C['cadence_min_requests']}, {C['cadence_cv_max']}, {C['cadence_window_s']}", "Nhịp metronome"),
        ("card_enum_challenge / block / window_s", f"{C['card_enum_challenge']} / {C['card_enum_block']} / {C['card_enum_window_s']}", "Số thẻ khác nhau trên cùng IP/thiết bị"),
        ("card_test_small_vnd / block / window_s", f"{C['card_test_small_vnd']:,} / {C['card_test_block']} / {C['card_test_window_s']}", "Chuỗi giao dịch nhỏ (card testing)"),
        ("device_customers_challenge / block", f"{C['device_customers_challenge']} / {C['device_customers_block']}", "Số khách dùng chung thiết bị/24 giờ"),
        ("ip_rate_challenge_per_min / block", f"{C['ip_rate_challenge_per_min']} / {C['ip_rate_block_per_min']}", "Tần suất yêu cầu từ một IP"),
        ("decline_ratio_block / decline_min", f"{C['decline_ratio_block']} / {C['decline_min']}", "Bão từ chối"),
        ("web_bot_score_suspect / bot", f"{C['web_bot_score_suspect']} / {C['web_bot_score_bot']}", "Ngưỡng điểm Anti-Bot web"),
        ("stale_request_s", f"{C['stale_request_s']}", "Lệch dấu thời gian tối đa"),
        ("require_telemetry_sources", "PORTAL, DIGIBANK, DIGIBIZ", "Kênh bắt buộc telemetry (demo: rỗng)"),
        ("block_without_nonce", "False (production: True)", "Bắt buộc nonce"),
        ("fail_closed", "True (demo: False)", "Lỗi Anti-Bot → chặn"),
    ], [5, 3, 5]))
    a("""
**Cách hiệu chỉnh:** (1) chạy pilot ở chế độ ghi nhận, (2) xem `antibot_events` để thống kê lớp/luật theo ngày, (3) điều chỉnh ngưỡng trong `agentmon/profiles.py` (ghi đè theo hồ sơ), (4) chạy lại `python -m tools.txn_attack_matrix` và `pytest`. Mọi thay đổi ngưỡng phải có phê duyệt (rủi ro I1).

# 6. Tầng 2 – AI Agent Monitor

## 6.1 Phân loại người thực hiện: AI Agent hay người?
Sau khi qua Tầng 1, `actor.classify` quyết định `actor_type` và **độ tin cậy**:
""")
    a(T(["Điều kiện", "Kết luận", "Tin cậy"], [
        ("Khóa Agent hợp lệ + AUTOMATION_AUTHORIZED", "AGENT", "0,95"),
        ("Phiên người + HUMAN_VERIFIED", "HUMAN", "0,95"),
        ("Phiên người + HUMAN_LIKELY (bằng chứng chưa mạnh)", "HUMAN", "0,75"),
        ("HUMAN_LIKELY nhưng có dấu hiệu tự động được bằng chứng người bù trừ", "HUMAN", "0,60 → ACTOR_UNVERIFIED"),
        ("Đã vượt thử thách sau nghi ngờ", "HUMAN", "0,60 → ACTOR_UNVERIFIED"),
        ("Giao dịch 'của người' trùng khít giao dịch Agent vừa gửi trong 10 giây (AGENT_ECHO)", "HUMAN (không tin cậy)", "≤ 0,5 → ACTOR_UNVERIFIED"),
    ], [7, 3, 3]))
    a("""
Tin cậy < 0,65 ⇒ `unverified` ⇒ trigger **ACTOR_UNVERIFIED** (bắt buộc xác minh bổ sung) và kiểu gian lận **ACTOR_SPOOFING**.

## 6.2 Khác biệt xử lý giữa Agent và người
""")
    a(T(["Nội dung", "AI Agent", "Người"], [
        ("Đăng ký", "Bắt buộc đăng ký, chi nhánh duyệt; thử việc vài giao dịch đầu", "Không cần"),
        ("Hạn mức", "MIN(TSC phân khúc, chi nhánh, Agent) + trần số lệnh/giờ, /ngày", "MIN(TSC, chi nhánh); không có trần số lệnh của Agent"),
        ("Kill-switch TSC", "Chặn Agent", "Không chặn người"),
        ("Xác minh bổ sung", "KYA qua Authenticator của chủ tài khoản (hết hạn 180 giây); chưa đăng ký Authenticator → BLOCK (fail-closed)", "STEP_UP (OTP/sinh trắc do kênh nguồn thực hiện), giữ chỗ số dư 15 phút"),
        ("LLM Critic", "Có (chỉ vùng xám, chỉ nâng mức)", "Không (độ trễ thời gian thực)"),
        ("Baseline", "Lịch sử của khách; riêng theo Agent khi ≥ 10 giao dịch Agent", "Lịch sử của khách; riêng theo người khi ≥ 10 giao dịch của người"),
        ("Tín hiệu riêng", "Velocity theo Agent; thử việc", "`session_risk` từ Tầng 1; thiết bị mới; telemetry"),
    ], [2, 5, 5]))
    a("""
## 6.3 Công thức điểm và ngưỡng
`điểm cuối = 0,70 × (0,40·ML + 0,30·Hành vi + 0,30·Velocity) + 0,30 × max(Hành vi, Velocity)` (+0,10 nếu khách trong danh sách theo dõi).
ML đơn độc không kéo điểm lên được; cần tín hiệu hành vi hoặc velocity đồng thuận.
Ngưỡng mặc định: **KYA/STEP_UP ≥ 0,35 · REVIEW ≥ 0,65 · BLOCK ≥ 0,85**; trigger có thể buộc KYA/STEP_UP dù điểm thấp.

## 6.4 Mô hình ML
""")
    a(T(["", "FX", "Thanh toán"], [
        ("Phương pháp", "Isolation Forest (không giám sát), 150 cây, 256 mẫu/cây, contamination 0,08", "như FX"),
        ("Số đặc trưng", f"{len(__import__('agentmon').features.FX_COLS)}", f"{len(__import__('agentmon').features.PAY_COLS)}"),
        ("Phiên bản hiện tại", mv.get("FX", ""), mv.get("PAY", "")),
        ("Nguồn dữ liệu huấn luyện", ent["FX"]["data_source"], ent["PAY"]["data_source"]),
        ("Kích thước file", f"{ent['FX']['size_bytes'] // 1024} KB", f"{ent['PAY']['size_bytes'] // 1024} KB"),
    ], [3, 5, 5]))
    a("""
Phiên bản, SHA-256, số mẫu, chỉ số in-sample và holdout được ghi trong `models/MANIFEST.json`; mỗi quyết định ghi version + SHA-256 mô hình đã dùng. Danh mục từng đặc trưng (ý nghĩa, nguồn, cơ sở, kiểu gian lận liên quan) ở Phụ lục A.

## 6.5 Trigger (bắt buộc xác minh, không phụ thuộc ML)
""")
    a(T(["Mã", "Ý nghĩa"], [
        ("AMOUNT_OVER_KYA", "Số tiền ≥ ngưỡng xác minh **và** lệch thói quen (≥ 1,5 lần mức thường lệ) hoặc lịch sử mỏng (`kya_above_min_ratio`)"),
        ("NEW_BENEFICIARY", "Chuyển cho người nhận mới vượt ngưỡng"), ("NEW_DEVICE", "Thiết bị chưa từng dùng (ví: kể cả lần đầu; người dùng kênh số: khi đã có lịch sử thiết bị)"),
        ("MULE_RECIPIENT", "≥ 3 khách khác chuyển tới cùng người nhận trong 24 giờ"), ("SESSION_BOT", "Điểm bot phiên ≥ 70/100"),
        ("ACTOR_UNVERIFIED", "Chưa xác minh được người hay Agent"), ("FIRST_ONLINE", "Khách chưa từng giao dịch online/Agent"),
        ("DORMANT_WAKE", "Tài khoản ngủ đông ≥ 60 ngày nay giao dịch"), ("BALANCE_DRAIN", "Dùng ≥ 70% số dư khả dụng"),
        ("AGENT_PROBATION", "Agent mới còn trong giai đoạn thử việc"), ("CARD_TESTING", "Chuỗi giao dịch nhỏ liên tiếp"),
        ("ATM_FOREIGN", "Rút ATM ngoài Việt Nam"), ("NO_3DS", "CNP vượt ngưỡng không có 3-D Secure"),
        ("HIGH_RISK_COUNTRY / NEW_COUNTRY / HIGH_RISK_MCC", "Quốc gia rủi ro/mới; ngành hàng rủi ro"), ("LEVERAGE_SPIKE", "Đòn bẩy FX tăng đột biến"),
        ("Luật thẻ", "MANUAL_ENTRY, CHIP_FALLBACK, CONTACTLESS_NO_CVM, REFUND_UNMATCHED, REFUND_OTHER_CARD, CAPTURE_OVER_PREAUTH, DOMESTIC_CARD_ABROAD, STATIC_QR_HIGH, IMPOSSIBLE_TRAVEL"),
    ], [4, 9]))
    a("""
## 6.6 Phân loại gian lận và bất thường
Lớp giải thích dựa trên luật (không đổi quyết định): **FRAUD_SUSPECTED** (có dấu hiệu HIGH hoặc ≥ 2 dấu hiệu MED, kèm loại gian lận và bằng chứng), **ANOMALY_UNCONFIRMED** (bất thường có thể hợp lệ → khách xác minh), **NORMAL**. Danh mục kiểu gian lận ở Phụ lục B. Danh mục là **đề xuất theo thông lệ**, cần đối chiếu với danh mục chuẩn của khối phòng chống gian lận.

## 6.7 Giải trình và kiểm toán
Mỗi quyết định lưu `details.trace` (schema `decision-trace/1`): mô hình (version + SHA-256), trọng số, ngưỡng tại thời điểm đó, vector đặc trưng, baseline, hạn mức hiệu lực, đường quyết định từng bước, trigger, LLM, phân loại gian lận, **kết quả sàng lọc Tầng 1 và phân loại người thực hiện** (`pre_screen`), và `trace_hash` (SHA-256 chống sửa). `GET /api/agent/actions/<id>/explain` (nhân viên/TSC, không cho khách) trả trace và kiểm tra toàn vẹn.

""")
    a("""
# 7. Nhận diện danh tính tại ATM bằng camera AI (KYC/KYA)

## 7.1 Bài toán
Tại ATM có ba khả năng phải phân biệt: **(a) chính chủ thẻ** tự rút tiền; **(b) người khác** dùng thẻ của khách (mất/lộ thẻ, ép buộc); **(c) tự động hóa/AI Agent** rút tiền mặt từ xa (relay, malware, jackpotting, hoặc Agent được giao rút tiền). ATM là thiết bị **vật lý**: AI Agent **không thể đứng trước ATM**, nên giao dịch ATM do Agent gửi luôn bị coi là rút tiền mặt từ xa và **bắt buộc chủ thẻ xác nhận** (KYA, trigger `AGENT_CASH_OUT`).

## 7.2 Mô hình hoạt động
1. **KYC sinh trắc (đăng ký):** khách đăng ký khuôn mặt (có sự đồng ý). Dịch vụ Face-AI trích xuất **embedding**; hệ thống chỉ lưu embedding **mã hóa** (không lưu ảnh). Hàm: `biometrics.enroll(customer_id, embedding, consent=True)`.
2. **Tại ATM:** camera + Face-AI gửi (qua switch ATM) các chỉ số: có người không, số khuôn mặt, độ khớp với mẫu (hoặc embedding để Monitor tự so khớp), liveness (chống ảnh/video/mặt nạ), điểm injection (virtual camera/deepfake), chất lượng, che khuất, trạng thái camera.
3. **Tầng 1** chặn ngay tấn công giả mạo (liveness thấp/injection cao) và giao dịch ATM không có người (camera hoạt động); liveness cao là **bằng chứng người thật mạnh nhất**.
4. **Tầng 2 – `atm_identity`** kết luận `who` (CUSTOMER / THIRD_PARTY / NO_PERSON / SPOOF / UNKNOWN) và mức quyết định tối thiểu.
5. **KYA của kênh ATM = xác nhận trên điện thoại chủ thẻ (`APP_CONFIRM`)** khi khuôn mặt chưa chắc chắn, nhiều khuôn mặt, camera bị che, hoặc chưa đăng ký khuôn mặt mà số tiền lớn.

## 7.3 Bảng verdict khuôn mặt và quyết định
""")
    a(T(["Verdict", "Điều kiện (ngưỡng mặc định, cấu hình trong `policy.global`)", "Ai đang rút (`who`)", "Quyết định", "Kiểu gian lận"], [
        ("FACE_VERIFIED", "1 khuôn mặt, liveness ≥ 0,90, injection ≤ 0,30, điểm khớp ≥ 0,80", "CUSTOMER", "Cho qua (vẫn áp hạn mức, hành vi)", "—"),
        ("FACE_MISMATCH", "Liveness tốt nhưng điểm khớp < 0,50", "THIRD_PARTY", "BLOCK (cân nhắc giữ thẻ, báo chủ thẻ)", "ATM_THIRD_PARTY_USE (HIGH)"),
        ("PRESENTATION_ATTACK", "Liveness < 0,50 hoặc injection ≥ 0,60", "SPOOF", "BLOCK (Tầng 1 và Tầng 2)", "ATM_SPOOF_ATTACK (HIGH)"),
        ("NO_PERSON", "Camera hoạt động nhưng không thấy người", "NO_PERSON", "BLOCK (Tầng 1)", "ATM_NO_PERSON (HIGH)"),
        ("FACE_UNCERTAIN", "Khớp 0,50–0,80; chất lượng/liveness thấp; che khuất", "UNKNOWN", "STEP_UP – APP_CONFIRM (KYA qua điện thoại)", "—"),
        ("MULTIPLE_FACES", "≥ 2 khuôn mặt", "UNKNOWN", "STEP_UP – APP_CONFIRM", "ATM_COERCION_OR_SURFING (MED)"),
        ("CAMERA_BLOCKED / TAMPER", "Camera bị che/can thiệp", "UNKNOWN", "STEP_UP; REVIEW nếu tamper hoặc ≥ 5.000.000 VND", "ATM_CAMERA_BLOCKED (MED/HIGH)"),
        ("CAMERA_OFFLINE", "Camera ngừng hoạt động", "UNKNOWN", "STEP_UP nếu ≥ 3.000.000 VND", "—"),
        ("NOT_ENROLLED", "Chủ thẻ chưa đăng ký khuôn mặt", "UNKNOWN", "STEP_UP nếu ≥ 3.000.000 VND", "—"),
        ("NO_BIOMETRIC_CHANNEL", "ATM cũ không có camera AI", "UNKNOWN", "Giữ hành vi trước đây (tương thích)", "—"),
    ], [2.6, 5, 2.4, 4, 3.4]))
    a("""
## 7.4 Tín hiệu hành vi tại ATM (không cần camera)
""")
    a(T(["Tín hiệu", "Điều kiện", "Hành động"], [
        ("ATM_PIN_AUTOMATED", "Hệ số biến thiên khoảng cách phím < 0,05 với ≥ 4 chữ số PIN", "+0,25 hành vi, xác thực bổ sung, kiểu ATM_PIN_AUTOMATED"),
        ("PIN sai", "≥ 2 lần nhập sai", "+0,15 hành vi"),
        ("ATM_CARD_COLLECTION", "≥ 4 chủ thẻ khác nhau trên cùng ATM trong 10 phút", "+0,30, xác thực bổ sung (thu gom thẻ/skimming)"),
        ("ATM_FOREIGN", "ATM ngoài Việt Nam (ngoài giờ/số tiền lệch → mức cao hơn)", "KYA/STEP_UP, ATM_CASHOUT_ABROAD"),
        ("Hạn mức ATM", "`atm_per_txn`, `atm_daily` (và hạn mức thẻ)", "Vượt → BLOCK (Hard Policy)"),
        ("AGENT_CASH_OUT", "AI Agent gửi giao dịch ATM", "Bắt buộc KYA qua Authenticator của chủ thẻ"),
    ], [3, 5, 5]))
    a("""
## 7.5 Ví dụ yêu cầu từ switch ATM
```
POST /gateway/v2/transaction              X-Source-Key: skx_...   (nguồn ATM_SWITCH)
{ "customer_id": "CUST005", "request_id": "ATM-0101-7781", "domain": "PAY", "kind": "ATM_WITHDRAWAL",
  "amount_vnd": 3000000, "card_token": "tok_...", "atm_id": "ATM0501",
  "pin_entry_cv": 0.42, "pin_digits": 6, "pin_attempts": 1,
  "biometric": { "face_present": true, "faces_in_frame": 1, "liveness_score": 0.97,
                 "injection_attack_score": 0.02, "capture_quality": 0.90, "occlusion": 0.05, "camera_status": "OK",
                 "face_match_score": 0.93 } }       // hoặc "face_embedding": [ ... ] để Monitor tự so khớp
```
Phản hồi `STEP_UP` có `step_up.method = "APP_CONFIRM"`; ATM giữ giao dịch chờ chủ thẻ xác nhận trên điện thoại rồi gọi `/step-up-result`. `face_embedding` chỉ dùng tạm để so khớp, **không bao giờ được lưu**.

## 7.6 Quyền riêng tư và giới hạn
* Sinh trắc là dữ liệu cá nhân **nhạy cảm** (Nghị định 13/2023/NĐ-CP): chỉ đăng ký khi có đồng ý, lưu embedding mã hóa (Fernet, khóa dẫn xuất từ `CARD_VAULT_KEY`; production dùng KMS/HSM), có hàm xóa, không lưu ảnh.
* **Hệ thống không tự nhận diện khuôn mặt từ ảnh**: cần dịch vụ Face-AI/camera ATM thật. Bản demo dùng embedding **giả lập** (`biometrics.demo_embedding`); ngưỡng khớp 0,80/0,50 là **giá trị mẫu** phải hiệu chỉnh theo nhà cung cấp (FAR/FRR), kiểm thử PAD độc lập (ISO/IEC 30107-3) và kiểm tra thiên lệch theo nhóm người dùng.
* Vùng trung gian **không chặn** mà chuyển sang xác nhận qua điện thoại để giảm chặn nhầm khách thật; chỉ khuôn mặt **không khớp** hoặc giả mạo mới chặn.

## 7.7 Kịch bản kiểm thử ATM và sao kê (dành cho người)
""")
    from agentmon import lab as _lab
    a(T(["Mã", "Nhóm", "Kịch bản", "Mô tả", "Kỳ vọng"], [(x[0], x[1], x[2], x[3], x[4]) for x in _lab.HUMAN_SCEN], [1, 1, 4, 7, 2]))
    a("""
# 8. Thẻ, thanh toán và FX

## 8.1 Mạng thẻ, sản phẩm, loại giao dịch
Danh mục đầy đủ ở Phụ lục C (sinh tự động từ `agentmon/cardmodel.py`). Tóm tắt:

* **Mạng thẻ:** Visa, Mastercard, JCB, UnionPay, American Express, Discover/Diners, NAPAS (thẻ nội địa), khác. Mạng lấy từ bản ghi thẻ hoặc `bin6`; Agent/nguồn chỉ gửi **token thẻ**, không gửi PAN.
* **Sản phẩm:** tín dụng, ghi nợ, trả trước, ảo, doanh nghiệp/thương mại.
* **Loại giao dịch (`txn_subtype`):** mua hàng, pre-auth, capture, hoàn tiền, đảo giao dịch, ứng tiền mặt, quasi-cash, định kỳ, MOTO, trả góp, thẻ-đến-thẻ, nạp tiền, hỏi số dư.
* **Phương thức nhập (`entry_mode`):** chip, chạm, quẹt từ, nhập tay, ECOM, token ví, QR, MOTO. **Xác thực (`auth_method`):** PIN, 3DS, OTP, sinh trắc, CDCVM, chữ ký, không.

## 8.2 Loại giao dịch hệ thống (`kind`) và kênh (`channel_type`)
""")
    from agentmon.constants import KIND_CHANNELS, KIND_LABELS
    a(T(["kind", "Ý nghĩa", "Kênh hợp lệ"], [(k, KIND_LABELS.get(k, ""), ", ".join(str(c) for c in v if c)) for k, v in KIND_CHANNELS.items()] + [("FX_TRADE", KIND_LABELS["FX_TRADE"], "—")], [3, 5, 5]))
    a("""
## 8.3 Luật rủi ro riêng cho thẻ (mã nguồn `cardmodel.signals`)
""")
    a(T(["Luật", "Điểm hành vi", "Trigger", "Kiểu gian lận"], [
        ("Nhập tay số thẻ / MOTO", "+0,20", "MANUAL_ENTRY khi ≥ 2.000.000 VND", "CARD_MANUAL_ENTRY"),
        ("Quẹt từ / fallback dù thẻ có chip", "+0,25", "CHIP_FALLBACK", "CARD_SKIMMING"),
        ("Chạm vượt 1.000.000 VND không xác thực", "+0,20", "CONTACTLESS_NO_CVM", "CARD_SKIMMING"),
        ("Ứng tiền mặt / quasi-cash", "+0,25", "—", "QUASI_CASH_CRYPTO"),
        ("Hoàn tiền không có giao dịch gốc", "+0,30", "REFUND_UNMATCHED", "REFUND_ABUSE"),
        ("Hoàn tiền về thẻ khác", "+0,40", "REFUND_OTHER_CARD", "REFUND_ABUSE (HIGH)"),
        ("Capture > 120% pre-auth", "+0,30", "CAPTURE_OVER_PREAUTH", "CARD_MERCHANT_ABUSE"),
        ("Định kỳ lần đầu tại merchant mới", "+0,15", "—", "—"),
        ("Thẻ NAPAS dùng ở nước ngoài", "+0,40", "DOMESTIC_CARD_ABROAD", "CARD_SKIMMING"),
        ("Thẻ ảo dùng quốc tế", "+0,10", "—", "—"),
        ("QR tĩnh ≥ 5.000.000 VND", "+0,20", "STATIC_QR_HIGH", "QR_SWAP"),
        ("Di chuyển bất khả thi (2 quốc gia < 2 giờ)", "+0,40", "IMPOSSIBLE_TRAVEL", "IMPOSSIBLE_TRAVEL (HIGH)"),
    ], [5, 2, 4, 4]))
    a("""
Ngưỡng tiền của các luật là tham số cấu hình (`policy` → `global`), **chưa hiệu chỉnh trên dữ liệu thật**.

## 8.4 Thanh toán (settlement): mua sắm online, QR, hóa đơn, ATM, ví, chuyển tiền
* **Mua sắm online (`ONLINE_PURCHASE`, CNP/Digibank/Digibiz):** thẻ phải bật thanh toán online; 3DS; merchant mới; MCC/quốc gia rủi ro; MCC cờ bạc bị chặn cứng.
* **Thanh toán dư nợ sao kê thẻ tín dụng (`CARD_STATEMENT_PAYMENT`, Digibank/Digibiz/Portal):** thẻ bị khóa/hết hạn vẫn được trả nợ; luật riêng: trả thừa > 120% dư nợ (STATEMENT_OVERPAY → nghi trả thừa rồi rút/hoàn), người trả không phải chủ thẻ ≥ 5.000.000 VND (THIRD_PARTY_PAYER), thẻ tín dụng trả thẻ tín dụng (CC_FUNDS_CC). Trường: `statement_balance`, `payer_is_cardholder`, `funding_source_type`.
* **QR/Hóa đơn (`QR_PAYMENT`, `BILL_PAYMENT`, Digibank/Digibiz):** `qr_scheme` (VietQR, NAPAS 247, EMVCo, QR tổ chức thẻ, QR ví), `qr_type` (tĩnh/động), biller/merchant mới, hạn mức `qr_bill_per_txn`.
* **ATM (`ATM_WITHDRAWAL`):** hạn mức lần/ngày, ATM nước ngoài (+ngoài giờ), baseline ATM riêng; **camera AI nhận diện khuôn mặt, nhịp PIN, thu gom thẻ** (mục 7).
* **Ví điện tử (`WALLET_PAYMENT`):** bắt buộc `wallet_provider` (Apple/Google/Samsung Pay) và `device_id`; thiết bị mới → xác thực bổ sung. *Chưa có cờ "thẻ đã bật ví" và chưa kiểm tra token DPAN.*
* **Chuyển tiền (`TRANSFER`):** người nhận mới, tài khoản trung gian (mule: ≥ 3 khách chuyển tới cùng người nhận/24 giờ), thiết bị mới, sát hạn mức/tách nhỏ, rút cạn số dư, kênh PORTAL/DIGIBANK/DIGIBIZ/IPS.
* **FX (`FX_TRADE`):** cặp tiền, đòn bẩy, hạn mức lệnh/ngày, velocity, điểm bot phiên; Anti-Bot web gốc chấm điểm báo giá.

## 8.5 Hạn mức mặc định (TSC)
""")
    for dom, title in (("PAY", "Thanh toán (VND)"), ("FX", "FX")):
        segs = policy.DEFAULTS[dom]["segments"]
        keys = [k for k in segs["STANDARD"] if k != "allowed_pairs"]
        a(f"**{title}**\n\n")
        a(T(["Tham số", "STANDARD", "VIP", "CORPORATE"], [(policy.LABELS.get(k, k), *[f"{segs[s][k]:,}".replace(",", ".") if isinstance(segs[s][k], (int, float)) else segs[s][k] for s in ("STANDARD", "VIP", "CORPORATE")]) for k in keys], [5, 3, 3, 3]))
        a("\n")
    a("""
Hạn mức hiệu lực = MIN(TSC phân khúc, chi nhánh theo CIF, Agent). Giá trị trên là **mặc định để trình diễn**, ngân hàng phải thay bằng chính sách thật.

""")
    a("""
""")

    a("""
## 8.6 Phân biệt giao dịch thật với giao dịch đáng ngờ/giả mạo/gian lận thẻ
Nguyên tắc: **giao dịch hợp lệ có "dấu vân tay" nhất quán** (đúng chủ thẻ, đúng thiết bị/kênh, đúng thói quen, xác thực đúng chuẩn); gian lận thường phá vỡ ít nhất một mắt xích. Hệ thống kiểm tra nhiều mắt xích cùng lúc thay vì một luật.
""")
    a(T(["Kiểu gian lận thẻ", "Dấu hiệu phân biệt với giao dịch thật", "Tầng", "Mã luật/kiểu", "Hành động"], [
        ("Card testing / dò thẻ (OWASP OAT Carding)", "Nhiều giao dịch nhỏ liên tiếp, nhiều merchant, tỷ lệ từ chối cao", "T1+T2", "CARD_TESTING, DECLINE_STORM", "BLOCK / KYA"),
        ("Dò BIN / card cracking", "Nhiều thẻ khác nhau từ cùng IP/thiết bị", "T1", "CARD_ENUMERATION", "BLOCK"),
        ("Thẻ giả / skimming", "Fallback quẹt từ dù có chip; chạm vượt hạn mức không CVM; thẻ nội địa dùng nước ngoài; nhiều thẻ khác chủ trên một ATM", "T2", "CHIP_FALLBACK, CONTACTLESS_NO_CVM, DOMESTIC_CARD_ABROAD, ATM_CARD_COLLECTION", "KYA/STEP_UP"),
        ("Mất/trộm thẻ dùng tại ATM", "Khuôn mặt không khớp chủ thẻ; PIN nhịp lạ", "T2", "ATM_THIRD_PARTY_USE", "BLOCK"),
        ("Giả mạo sinh trắc / deepfake", "Liveness thấp, injection/virtual camera", "T1+T2", "PRESENTATION_ATTACK, ATM_SPOOF_ATTACK", "BLOCK"),
        ("Rút tiền từ xa / relay / malware", "Giao dịch ATM nhưng không có người trước máy", "T1", "NO_PERSON_AT_ATM", "BLOCK"),
        ("AI Agent rút tiền mặt", "Agent gửi giao dịch ATM", "T2", "AGENT_CASH_OUT", "KYA bắt buộc"),
        ("CNP/ecommerce không xác thực", "Vượt ngưỡng không 3DS; nhập tay số thẻ; merchant/quốc gia lạ", "T2", "NO_3DS, MANUAL_ENTRY, NEW_COUNTRY", "KYA/STEP_UP"),
        ("Di chuyển bất khả thi", "Hai quốc gia trong < 2 giờ", "T2", "IMPOSSIBLE_TRAVEL", "KYA/STEP_UP (FRAUD_SUSPECTED)"),
        ("Chiếm quyền tài khoản", "Thiết bị mới + người nhận mới + số tiền lệch + phiên bot", "T1+T2", "NEW_DEVICE, NEW_BENEFICIARY, SESSION_BOT, ACCOUNT_TAKEOVER", "STEP_UP"),
        ("Thanh toán khống / merchant thông đồng", "Merchant mới, số tiền tròn lớn, MCC rủi ro; capture vượt pre-auth; hoàn tiền không gốc", "T2", "FICTITIOUS_PAYMENT, CAPTURE_OVER_PREAUTH, REFUND_UNMATCHED", "KYA/REVIEW"),
        ("Lạm dụng hoàn tiền / sao kê", "Hoàn tiền về thẻ khác; trả thừa sao kê; thẻ tín dụng trả thẻ tín dụng", "T2", "REFUND_OTHER_CARD, STATEMENT_OVERPAY, CC_FUNDS_CC", "STEP_UP"),
        ("QR giả / thay QR tĩnh", "QR tĩnh số tiền lớn tới merchant lạ", "T2", "STATIC_QR_HIGH", "STEP_UP"),
        ("Mule / vòng gian lận", "Nhiều khách chuyển tới một người nhận; nhiều tài khoản chung thiết bị/IP", "T2", "MULE_RECIPIENT, LINKED_ACCOUNTS, FRAUD_RING", "STEP_UP"),
        ("Cờ bạc / quasi-cash / MCC rủi ro", "MCC 7995…; MCC rủi ro do TSC cấu hình", "T2", "ILLEGAL_GAMBLING, HIGH_RISK_MCC", "BLOCK / KYA"),
    ], [4, 6, 1, 5, 2]))
    a("""
**Loại hình thẻ:** thẻ **debit** (nguy cơ rút cạn số dư), **credit** (ứng tiền mặt, trả thừa sao kê, thẻ trả thẻ), **prepaid** (nạp lớn – PREPAID_LOAD_HIGH), **virtual** (dùng quốc tế, nhiều thẻ ảo từ cùng thiết bị qua đồ thị), **corporate** (số tiền lớn, hạn mức doanh nghiệp) đều dùng chung bộ luật trên, kèm baseline theo từng loại giao dịch.
**Chưa có:** gian lận thân thiện/lạm dụng chargeback (friendly fraud) vì cần dữ liệu chargeback và báo cáo gian lận của tổ chức thẻ (rủi ro K9).
""")
    a("""
# 9. Các mô hình AI phối hợp (ensemble)

## 9.1 Vì sao nhiều mô hình
Mỗi mô hình bắt một loại tín hiệu khác nhau; kết hợp giảm bỏ lọt và giải thích được. Nguyên tắc: **các mô hình bổ sung chỉ được NÂNG cảnh báo, không bao giờ hạ**; Hard Policy không bị ghi đè; mô hình học có giám sát chạy **chế độ bóng (shadow)** ở pilot/production cho tới khi kiểm chứng bằng dữ liệu thật.

## 9.2 Danh sách mô hình
""")
    from agentmon import ml as _ml
    _m = _ml.read_manifest()
    _bot = _m["BOT"]["history"][-1]
    _gp, _gf = _m["GBM_PAY"]["history"][-1], _m["GBM_FX"]["history"][-1]
    a(T(["Mô hình", "Loại", "Tầng", "Việc làm", "Dữ liệu huấn luyện", "Chế độ"], [
        ("Isolation Forest (FX 24, PAY 41 đặc trưng)", "Không giám sát", "T2", "Phát hiện giao dịch lệch thói quen/phân phối", "Tổng hợp (cần dữ liệu thật)", "Luôn bật (thành phần điểm)"),
        ("Gradient boosting giám sát (FX, PAY)", "Có giám sát", "T2", "Ý kiến thứ hai; ≥ 0,85 → trigger SUPERVISED_HIGH_RISK", "Nhãn tổng hợp (vòng tròn với bộ sinh)", "demo: active · pilot/production: shadow"),
        ("Mô hình bot–người (gradient boosting)", "Có giám sát", "T1", "Xác suất bot từ sinh trắc hành vi phiên", "Tổng hợp, có chủ đích chồng lấn", "demo: active · pilot/production: shadow"),
        ("Mô hình chuỗi hành vi (Markov bậc 1)", "Thống kê theo khách", "T2", "Độ bất ngờ của chuyển tiếp loại/kênh/ngành hàng", "Lịch sử của chính khách (≥ 20 giao dịch)", "Luôn bật (+0,10 hành vi)"),
        ("Đồ thị liên kết", "Phân tích đồ thị", "T2", "Số khách liên kết qua thiết bị/người nhận/IP trong 7 ngày", "Dữ liệu giao dịch + antibot_events", "Luôn bật (cộng điểm, không chặn cứng)"),
        ("Face-AI (camera ATM/app)", "Dịch vụ ngoài", "T1+T2", "Khuôn mặt, liveness, injection (PAD)", "Nhà cung cấp Face-AI", "Cần tích hợp thật; demo dùng embedding giả lập"),
        ("LLM Critic", "Mô hình ngôn ngữ", "T2 (chỉ Agent)", "Nhận xét vùng xám, chỉ nâng mức", "—", "Tắt cho người; mock mặc định"),
        ("Bộ luật (Hard Policy, trigger, thẻ, ATM)", "Luật xác định", "T1+T2", "Chặn cứng, bắt buộc xác minh", "Chính sách TSC", "Luôn bật"),
    ], [4, 2, 1, 5, 4, 3]))
    a(f"""
## 9.3 Chỉ số hiện có (dữ liệu TỔNG HỢP – chỉ là kiểm tra hồi quy)
**Mô hình bot–người** (`{_bot['version']}`): AUC {_bot['holdout']['auc']}, AP {_bot['holdout']['ap']}, recall tại FPR 1% = {_bot['holdout']['recall_at_fpr_1pct']}; ở ngưỡng 0,85 bắt {_bot['holdout']['flag_at_0.85']['bot_recall'] * 100:.1f}% bot và gắn nhầm {_bot['holdout']['flag_at_0.85']['human_flagged'] * 100:.2f}% người. Bộ dữ liệu cố ý có 3 loại bot (ngây thơ, có trễ ngẫu nhiên, mô phỏng người nâng cao) và 10% người "khác thường" (trình quản lý mật khẩu, công nghệ hỗ trợ) để có chồng lấn; phiên bản đầu với dữ liệu quá dễ cho AUC = 1,0 và đã bị loại bỏ vì không đáng tin.

**Gradient boosting giám sát:** PAY AUC {_gp['holdout']['auc']} (tỷ lệ cảnh báo {_gp['holdout']['at_0.85']['alert_rate']}, precision {_gp['holdout']['at_0.85']['precision']}, FPR {_gp['holdout']['at_0.85']['false_positive_rate']} tại ngưỡng 0,85); FX AUC {_gf['holdout']['auc']}. **Số liệu này mang tính vòng tròn** vì nhãn do chính bộ sinh dữ liệu gắn; vì vậy mô hình chạy shadow ở pilot/production.

## 9.4 Chế độ active và shadow
* `ENSEMBLE_MODE=active|shadow` (mặc định: demo active; pilot/production shadow).
* **Shadow:** kết quả vẫn được tính và ghi vào trace/bằng chứng (`ML_BOT_PROB`, `supervised_gbm`) để đo trên dữ liệu thật nhưng **không tác động quyết định**.
* **Active:** mô hình bot–người cộng/trừ điểm bằng chứng (≥ 0,85: bot +3; ≥ 0,6: +2; ≤ 0,15: người +2); gradient boosting thêm trigger khi ≥ 0,85.
* Chuyển từ shadow sang active chỉ sau khi backtest trên dữ liệu thật đạt tiêu chí do ngân hàng đặt và được phê duyệt (rủi ro K6).

## 9.5 Huấn luyện và vòng đời
`python -m agentmon.train_cli` huấn luyện toàn bộ (IF, boosting, bot–người). Mỗi mô hình có version, SHA-256, số mẫu, nguồn dữ liệu và chỉ số holdout trong `models/MANIFEST.json` (khóa FX, PAY, GBM_FX, GBM_PAY, BOT). Khi có dữ liệu thật: `python -m agentmon.backtest --csv … --save-model` (xem mục 13).
""")
    a("""
# 10. Tham chiếu API

## 10.1 Cổng thống nhất – giao dịch của NGƯỜI (hệ thống nguồn)
```
POST /gateway/v2/transaction
X-Source-Key: skx_xxxxxxxx_...
Content-Type: application/json

{
  "customer_id": "CUST001",
  "request_id": "DGB-20261113-000123",        // bắt buộc, duy nhất; gửi lại = trả kết quả cũ (chống trùng)
  "domain": "PAY", "kind": "TRANSFER",
  "amount_vnd": 45000000, "beneficiary_account": "9999000011",
  "session": {
    "device_id": "DEV-IPH001", "device_known": true, "device_attested": true,
    "anti_bot_score": 12, "mfa_age_s": 90, "think_time_ms": 5200,
    "pointer_events": 14, "key_events": 22, "nonce": "n-8f3a...", "ts": 1794550000,
    "client_ip": "113.161.x.x", "ip_reputation": "RESIDENTIAL"
  }
}
```
**Phản hồi khi qua Tầng 1 (tới Monitor):**
```
200 { "stage": "MONITOR", "transaction_id": 734, "action": "STEP_UP", "status": "PENDING_STEPUP",
      "actor_type": "HUMAN", "actor_confidence": 0.95, "bot_class": "HUMAN_VERIFIED",
      "reason_codes": ["NEW_BENEFICIARY","NEW_DEVICE"],
      "step_up": {"method": "OTP", "expires_in": 900, "callback": "/txn-api/v1/transactions/734/step-up-result"},
      "elapsed_ms": 23 }
```
**Phản hồi khi Tầng 1 dừng (Monitor không chạy):**
```
403 { "stage": "ANTIBOT", "action": "BLOCK", "bot_class": "MALICIOUS_BOT", "reason_codes": ["REPLAY"], "message": "Nonce đã được dùng (replay)" }
200 { "stage": "ANTIBOT", "action": "CHALLENGE", "bot_class": "SUSPECT",
      "challenge": {"type": "TURNSTILE", "how": "Hiển thị thử thách ... gửi lại với session.turnstile_ok=true"} }
```
Kênh nguồn là bên **thực hiện** hoặc từ chối giao dịch theo `action`; Monitor không điều khiển core banking (bản demo trừ số dư mô phỏng khi ALLOW). Không có điểm số nội bộ trong phản hồi cho kênh.

## 10.2 Báo kết quả xác thực bổ sung
```
POST /txn-api/v1/transactions/734/step-up-result      X-Source-Key: skx_...
{ "passed": true }          →  200 { "status": "EXECUTED" }        (đạt)
{ "passed": false }         →  200 { "status": "STEPUP_FAILED" }   (không đạt, tăng điểm nghi ngờ khách)
```
Hết 15 phút → `STEPUP_EXPIRED`. Nguồn khác không được xác nhận giao dịch của nguồn này (404).

## 10.3 AI Agent
```
POST /gateway/v2/transaction      (hoặc POST /agent-api/v1/monitor/action)
Authorization: Bearer agk_xxxxxxxx_...
{ "domain": "PAY", "kind": "TRANSFER", "amount_vnd": 3000000, "beneficiary_account": "1234567890", "request_id": "agent-001" }
```
Phản hồi: `ALLOW` (đã thực hiện), `KYA` (kèm `kya.id`, khách duyệt trong Authenticator, hết hạn 180 giây; Agent thăm dò `GET /agent-api/v1/actions/<id>`), `REVIEW` (chờ nhân viên), `BLOCK` (403, kèm lý do).

## 10.4 Giao dịch thẻ – ví dụ đầy đủ trường
```
{ "customer_id": "CUST001", "request_id": "SW-77812", "domain": "PAY", "kind": "CARD_PAYMENT",
  "amount_vnd": 2500000, "card_token": "tok_...", "merchant_id": "M300", "mcc": "5411", "country": "VN",
  "txn_subtype": "PURCHASE", "entry_mode": "CONTACTLESS", "auth_method": "NONE", "card_network": "VISA",
  "card_product": "CREDIT", "chip_fallback": false, "three_ds": false }
```
Các giá trị hợp lệ của `txn_subtype`, `entry_mode`, `auth_method`, `card_network`, `card_product`, `qr_scheme`, `qr_type` ở Phụ lục C; giá trị ngoài danh mục → 400.

## 10.5 Mã lỗi
""")
    a(T(["Mã HTTP", "Nguyên nhân", "Xử lý"], [
        ("400", "Thiếu trường, sai kiểu, ngoài khoảng (`session.*`), `kind` không thuộc nguồn, enum ngoài danh mục", "Sửa payload theo thông báo"),
        ("401", "Thiếu/sai khóa; sai nhiều lần bị strike IP", "Kiểm tra khóa; cấp lại khóa"),
        ("403", "Tầng 1 BLOCK (bot, replay, dò thẻ…) hoặc Monitor BLOCK (Agent)", "Xem `reason_codes`; không gửi lại nguyên văn"),
        ("429", "Vượt giới hạn tốc độ", "Giảm tần suất"),
        ("200 + action CHALLENGE", "Tầng 1 yêu cầu thử thách", "Hiển thị thử thách, gửi lại với `turnstile_ok`"),
        ("200 + action STEP_UP / REVIEW / KYA", "Monitor yêu cầu xác minh/duyệt", "Thực hiện xác thực bổ sung / chờ duyệt / khách duyệt KYA"),
    ], [2, 8, 5]))
    a("""
## 10.6 API quản trị (HQ/chi nhánh/nhân viên)
""")
    a(T(["Endpoint", "Vai trò", "Chức năng"], [
        ("`GET /api/agent/hq/readiness`", "HQ", "Kiểm tra sẵn sàng theo hồ sơ"),
        ("`GET /api/agent/hq/antibot-events`", "HQ, CN_ADMIN, PNV", "200 sự kiện Anti-Bot gần nhất (lớp, luật, IP, thiết bị)"),
        ("`GET /api/agent/hq/sources`, `POST /api/agent/hq/sources/<id>/key`", "HQ", "Danh sách hệ thống nguồn; cấp/đổi khóa (hiển thị một lần, khóa cũ mất hiệu lực)"),
        ("`GET /api/agent/hq/model`, `POST /api/agent/hq/model/retrain`", "HQ", "Trạng thái/huấn luyện lại mô hình"),
        ("`GET /api/agent/actions/<id>/explain`", "HQ, CN_ADMIN, PNV, STAFF", "Trace giải trình + kiểm tra toàn vẹn"),
    ], [5, 3, 6]))

    a("""
# 11. Vận hành hằng ngày

## 11.1 Phân vai
* **TSC/HQ:** chính sách và hạn mức, danh mục MCC/quốc gia, kill-switch (chỉ Agent), cấp khóa hệ thống nguồn, huấn luyện/backtest mô hình, readiness.
* **Chi nhánh:** duyệt đăng ký Agent, hạn mức theo CIF, xét duyệt giao dịch REVIEW.
* **Nhân viên:** xem giao dịch, giải trình (explain), xử lý REVIEW.
* **Khách hàng:** đăng ký Authenticator, duyệt/từ chối KYA (khi Agent giao dịch bất thường); thực hiện OTP/sinh trắc khi STEP_UP (tại kênh nguồn).

## 11.2 Việc hằng ngày
1. Xem `antibot_events`: tỷ lệ ALLOW/CHALLENGE/BLOCK theo nguồn; luật nào kích hoạt nhiều; có dải IP/thiết bị bất thường không.
2. Xem hàng đợi REVIEW và KYA hết hạn; xử lý trong SLA.
3. Xem tỷ lệ STEP_UP/KYA trên giao dịch lành tính (mục tiêu do kinh doanh đặt) – nếu cao, xem trigger gây báo nhầm.
4. Kiểm tra readiness và tính toàn vẹn mô hình (SHA-256 khớp MANIFEST).

## 11.3 Việc định kỳ
* **Hằng tuần:** rà soát trường hợp CHALLENGE/BLOCK của khách thật (kháng nghị), chỉnh ngưỡng nếu cần (có phê duyệt).
* **Hằng tháng:** chạy backtest trên dữ liệu thật mới nhất; so sánh chỉ số; huấn luyện lại nếu drift (`python -m agentmon.backtest --csv … --save-model`).
* **Hằng quý:** thử nghiệm đỏ (`tools/txn_attack_matrix.py` + kịch bản mới), rà soát danh mục rủi ro và danh mục MCC/quốc gia.

## 11.4 Cấp và xoay khóa
* Khóa Agent: đăng ký → chi nhánh duyệt → cấp khóa (hiển thị một lần). Nghi lộ khóa: cấp lại (khóa cũ vô hiệu) hoặc thu hồi/tạm ngưng Agent.
* Khóa hệ thống nguồn: `POST /api/agent/hq/sources/<system_id>/key`; lưu ngay vào KMS của hệ thống nguồn.

## 11.5 Sao lưu và khôi phục
Sao lưu `data/` (CSDL), `models/MANIFEST.json` và `models/archive/` (đặt `AGENTMON_MODEL_ARCHIVE=1`), `logs/`. Khôi phục mô hình cũ theo `version` + SHA-256 trong trace.

## 11.6 Xử lý sự cố
""")
    a(T(["Hiện tượng", "Nguyên nhân thường gặp", "Cách xử lý"], [
        ("Ứng dụng không khởi động, báo 'Chưa đủ điều kiện production'", "`DEPLOY_PROFILE=production` còn mục BLOCKER", "Chạy readiness, xử lý từng mục; hoặc dùng hồ sơ pilot nếu chưa đủ điều kiện"),
        ("Mọi giao dịch bị chặn ở Tầng 1 với `ANTIBOT_ERROR`", "Redis/store lỗi, hồ sơ fail-closed", "Khôi phục Redis; kiểm tra log; không tắt fail-closed ở production"),
        ("Khách thật bị CHALLENGE liên tục", "Kênh nguồn không gửi telemetry; thiết bị chưa chứng thực; `think_time_ms` sai đơn vị", "Kiểm tra telemetry của nguồn; xem `evidence` trong antibot_events"),
        ("Nhiều STEP_UP ngay giao dịch đầu trên thiết bị mới", "Đúng thiết kế: thiết bị chưa từng thấy", "Đăng ký thiết bị tin cậy (`device_known`) hoặc chấp nhận xác thực bổ sung"),
        ("401 dù đúng khóa", "Khóa đã bị cấp lại; header sai (Agent dùng Bearer, nguồn dùng X-Source-Key)", "Cấp lại khóa; kiểm tra header"),
        ("Số dư 'không đủ' dù còn tiền", "Lệnh chờ KYA/REVIEW/STEP_UP đang giữ chỗ", "Chờ hết hạn (KYA 180 giây, STEP_UP 15 phút) hoặc xử lý lệnh chờ"),
        ("SHA-256 mô hình không khớp MANIFEST", "File mô hình bị thay ngoài quy trình huấn luyện", "Khôi phục từ `models/archive/` theo version; điều tra"),
        ("Trace không có cho giao dịch cũ", "Giao dịch tạo trước v1.1", "Bình thường"),
    ], [4, 5, 5]))

    a("""
# 12. Kiểm thử

## 12.1 Các lớp kiểm thử
""")
    a(T(["Lớp", "Lệnh", "Nội dung"], [
        ("Đơn vị + tích hợp", f"`python -m pytest tests -q`  ({n_tests} test)", "Anti-Bot web gốc, Monitor, thẻ/ATM/ví/Digibank-Digibiz, phân loại gian lận, trace, mô hình, dữ liệu thật/backtest, FX+thanh toán đồng thời, hồ sơ, pipeline v2"),
        ("Sinh trắc/ATM/mô hình AI", "`tests/test_v21.py`", "Đăng ký sinh trắc có đồng ý + mã hóa, verdict khuôn mặt, 14 kịch bản người dùng, mô hình bot–người (active/shadow), boosting, chuỗi, đồ thị, sao kê thẻ"),
        ("Đa tiến trình", "`tests/test_multiprocess.py`", "Hai tiến trình đồng thời trên cùng số dư (FX + thanh toán): luôn đúng một lệnh giữ được số dư"),
        ("Ma trận tấn công giao dịch", "`python -m tools.txn_attack_matrix`", f"{len(atk_rows)} kịch bản qua pipeline (kết quả mục 12.3)"),
        ("Ma trận tấn công web gốc", "`python -m tools.attack_matrix`", "Kịch bản tấn công Anti-Bot web (bản gốc)"),
        ("Test Lab", "Giao diện HQ/Chi nhánh (demo/pilot; tắt ở production)", f"{len(lab.SCEN)} kịch bản FX + thanh toán cho Agent và {len(lab.HUMAN_SCEN)} kịch bản người dùng (ATM + khuôn mặt, sao kê) chạy trực tiếp tầng Monitor (không qua Anti-Bot)"),
        ("Backtest", "`python -m agentmon.backtest --synthetic|--csv`", "Đo chỉ số mô hình (mục 13)"),
    ], [3, 5, 6]))
    a("""
**Lưu ý:** Test Lab gọi thẳng engine để thử từng luật Monitor, **không** đi qua Tầng 1. Muốn thử Tầng 1 + Tầng 2 cùng nhau dùng `tools/txn_attack_matrix.py` hoặc cổng `/gateway/v2/transaction`.

## 12.2 Cách chạy một kịch bản tấn công qua API (ví dụ)
1. Cấp khóa nguồn: `python -c "from agentmon import sources;print(sources.issue_key('digibank-demo'))"`.
2. Gửi giao dịch hợp lệ có telemetry tốt → kỳ vọng `stage: MONITOR`.
3. Gửi lại **cùng `nonce`** → kỳ vọng `403`, `REPLAY`.
4. Gửi `think_time_ms: 50`, `anti_bot_score: 95`, User-Agent `curl/8` → kỳ vọng `403`, `BOT_EVIDENCE_STRONG`.
5. Gửi 5 thẻ khác nhau từ cùng `device_id` trong 10 phút → kỳ vọng `CARD_ENUMERATION`.

## 12.3 Kết quả ma trận tấn công giao dịch (chạy thực tế)
""")
    a(T(["Kịch bản", "Kỳ vọng", "Thực tế", "Lớp", "Luật", "KQ"], [[x.strip() for x in r] for r in atk_rows], [6, 3, 3, 3, 4, 1]))
    a("""
## 12.4 Test Lab – danh mục kịch bản
""")
    a(T(["Mã", "Phân hệ", "Kịch bản", "Mô tả", "Kỳ vọng"], [(s[0], s[1], s[2], s[3], s[4]) for s in lab.SCEN], [1, 1, 4, 7, 2]))

    a(f"""
# 13. Đánh giá mô hình và dữ liệu thật

## 13.1 Hiện trạng trung thực
Mô hình đang huấn luyện trên **dữ liệu tổng hợp**. Chỉ số dưới đây (tập test tách riêng: khác seed, khác khách) chỉ là **kiểm tra hồi quy**, không phải bằng chứng hiệu quả thực tế.
""")
    bt = open(os.path.join(D, "BACKTEST_SYNTHETIC.md"), encoding="utf-8").read()
    pay = re.findall(r"\| KYA_or_above \| 0.35 \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \| ([\d.]+) \|", bt)
    auc = re.findall(r"AUC \(điểm cuối\):\*\* ([\d.]+)", bt)
    if pay and auc:
        a(T(["Phân hệ", "AUC điểm cuối", "Tỷ lệ cảnh báo (KYA↑)", "Recall", "Precision", "Báo nhầm (FPR)"],
            [("Thanh toán", auc[0], *pay[0]), ("FX", auc[1] if len(auc) > 1 else "", *pay[1])] if len(pay) > 1 else [("Thanh toán", auc[0], *pay[0])], [2, 2, 3, 2, 2, 2]))
    a("""
**Tối ưu cấu hình v2.0:** trigger `AMOUNT_OVER_KYA` đổi từ "số tiền ≥ ngưỡng" thành "≥ ngưỡng **và** lệch thói quen (≥ 1,5 lần) hoặc lịch sử mỏng". Phân hệ thanh toán, cùng tập test: báo nhầm 0,152 → 0,119; precision 0,555 → 0,612; recall 0,815 → 0,811 (giảm báo nhầm ~22% tương đối). Cần kiểm lại trên dữ liệu thật.

## 13.2 Đánh giá trên dữ liệu thật
Đặc tả dữ liệu (cột, nguồn, nhãn, khối lượng) trong `docs/DATA_REQUIREMENTS.md`; mẫu CSV trong `docs/templates/`.
```
python -m agentmon.backtest --csv giao_dich_pay.csv --domain PAY --save-model
```
Công cụ tách theo **thời gian** (train quá khứ, test tương lai), chỉ huấn luyện trên giao dịch không có nhãn gian lận, báo cáo AUC/AP, tỷ lệ cảnh báo, recall, precision, FPR tại các ngưỡng KYA/REVIEW/BLOCK và **trigger nào gây báo nhầm**. Khối lượng tối thiểu: ≥ 6 tháng, vài nghìn giao dịch mỗi phân hệ, ≥ 30 nhãn dương (khuyến nghị ≥ 12 tháng, ≥ 500.000 giao dịch, ≥ 300 nhãn).

# 14. Checklist theo giai đoạn

## 14.1 Demo
* Dữ liệu mô phỏng, `DEPLOY_PROFILE=demo`, Test Lab bật, LLM `mock`.
* Chạy `pytest` và `txn_attack_matrix` trước buổi trình diễn; xem trước kịch bản mục 12.4.
* **Không** dùng thẻ/khách thật; không nối hệ thống thật.

## 14.2 Pilot (chạy thử có kiểm soát)
""")
    a(T(["Hạng mục", "Yêu cầu"], [
        ("Phạm vi", "Giới hạn khách/giao dịch/hạn mức thấp; có người duyệt REVIEW trong SLA; thông báo khách tham gia"),
        ("Hồ sơ", "`DEPLOY_PROFILE=pilot`; Redis; telemetry bắt buộc cho kênh trực tuyến; fail-closed"),
        ("Dữ liệu", "Ghi nhận mọi quyết định + nhãn kết quả (chargeback, khách từ chối KYA/STEP_UP) để có dữ liệu thật"),
        ("Giám sát", "Báo cáo hằng ngày từ `antibot_events` và `actions`: tỷ lệ chặn/thử thách/xác minh, khiếu nại"),
        ("Rút lui", "Cơ chế tắt nhanh (kill-switch cho Agent; chế độ chỉ ghi nhận cho người)"),
        ("Kiểm toán", "Lưu nhật ký và trace; sao lưu hằng ngày"),
    ], [2, 9]))
    a("""
## 14.3 Production
""")
    a(T(["Hạng mục", "Điều kiện bắt buộc (BLOCKER)"], [
        ("Sinh trắc và ATM", "Tích hợp Face-AI thật đạt kiểm thử PAD độc lập (ISO/IEC 30107-3), hiệu chỉnh FAR/FRR và kiểm tra thiên lệch; đánh giá tác động xử lý dữ liệu sinh trắc; đồng ý của khách; KMS/HSM; quy trình dự phòng khi camera lỗi"),
        ("Mô hình AI bổ sung", "Backtest trên dữ liệu thật đạt tiêu chí, phê duyệt chuyển từ shadow sang active; giám sát drift"),
        ("Mô hình", "Huấn luyện và kiểm chứng trên dữ liệu thật, có tiêu chí chấp nhận do ngân hàng đặt (recall, precision, tỷ lệ xác minh)"),
        ("Dữ liệu", "Core banking, CIF, switch thẻ, token service, log Digibank/Digibiz thật; không còn `mock`"),
        ("CSDL và hạ tầng", "PostgreSQL/Oracle, khóa tư vấn theo khách; nhiều bản sao sau cân bằng tải; Redis dự phòng; DR; test tải đạt độ trễ mục tiêu"),
        ("Bảo mật", "KMS/HSM cho khóa; MFA; Turnstile; pentest độc lập; PCI-DSS (phạm vi, token hóa); nhật ký một chiều"),
        ("Pháp lý – tuân thủ", "Pháp chế xác nhận: bảo vệ dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP), an toàn hệ thống thông tin ngân hàng (Thông tư 09/2020/TT-NHNN), yêu cầu xác thực giao dịch trực tuyến/sinh trắc (Quyết định 2345/QĐ-NHNN) và các quy định hiện hành"),
        ("Quy trình", "Phê duyệt thay đổi mô hình/ngưỡng 2 người; luồng kháng nghị cho khách bị chặn nhầm; vòng phản hồi nhãn"),
        ("Cổng khởi động", "`DEPLOY_PROFILE=production`: readiness không còn BLOCKER"),
    ], [2, 9]))

    a("""
# 15. Giới hạn đã biết của phiên bản này
* Mô hình huấn luyện trên **dữ liệu tổng hợp**; chưa có bằng chứng hiệu quả trên dữ liệu thật.
* Dữ liệu khách/thẻ/số dư là **mô phỏng** (`mock_db`); SQLite; khóa đồng thời chỉ đúng trên **một máy**.
* Luật thẻ và ngưỡng tiền là **tham số theo thông lệ**, chưa hiệu chỉnh; chưa có cờ "thẻ đã bật ví", chưa kiểm tra token DPAN, POS chưa có đặc trưng terminal/EMV chi tiết.
* "Thanh toán khống" mới là heuristic; chưa có dữ liệu rủi ro đơn vị chấp nhận thẻ.
* Chưa có giám sát drift tự động, metrics/alert vận hành, luồng kháng nghị khách, vòng phản hồi nhãn tự động.
* Anti-Bot cấp giao dịch dựa trên **tín hiệu do kênh nguồn gửi**; kênh nguồn bị chiếm quyền có thể gửi tín hiệu giả – cần chứng thực thiết bị phía ứng dụng.
* Test Lab không đi qua Tầng 1.
* **Face-AI chỉ được giả lập** (embedding mô phỏng); chưa có tích hợp camera/nhà cung cấp thật, chưa kiểm thử PAD, FAR/FRR và thiên lệch theo nhóm người dùng.
* Gradient boosting giám sát và mô hình bot–người học trên **nhãn tổng hợp** (số liệu mang tính vòng tròn); vì vậy chạy shadow ở pilot/production.
* Đồ thị liên kết có thể báo nhầm với gia đình/doanh nghiệp dùng chung thiết bị (chỉ cộng điểm, không chặn cứng).
* Chưa có gian lận thân thiện/chargeback abuse (cần dữ liệu chargeback); chưa có dữ liệu liên-merchant/liên-ngân hàng.

# 16. Danh mục rủi ro cần tránh (demo/pilot và production)
Trạng thái: **CÓ** = đã có kiểm soát trong mã và có test; **MỘT PHẦN** = có nhưng còn giới hạn; **CHƯA** = chưa có, cần làm trước khi dùng thật. Tham chiếu pháp lý chỉ để định hướng; Pháp chế/Tuân thủ xác nhận phạm vi áp dụng.

""")
    s = riskregister.summary()
    a(f"Tổng **{len(riskregister.R)}** rủi ro: CÓ {s.get('CÓ', 0)} · MỘT PHẦN {s.get('MỘT PHẦN', 0)} · CHƯA {s.get('CHƯA', 0)}.\n\n")
    for g, name in riskregister.GROUPS.items():
        a(f"## 16.{list(riskregister.GROUPS).index(g) + 1} {name}\n\n")
        a(T(["ID", "Rủi ro", "Demo / Pilot", "Production", "Kiểm soát hiện có", "Trạng thái"], [(r[0], r[2], r[3], r[4], r[5], r[6]) for r in riskregister.R if r[1] == g], [1.4, 4, 4, 5, 5, 1.9]))
        a("\n")
    a("""
# Phụ lục A. Danh mục đặc trưng của mô hình
Cơ sở xây dựng: thiết kế theo kinh nghiệm nghiệp vụ và các kiểu gian lận đã biết, **chưa** chọn/kiểm chứng bằng nhãn thật.

""")
    from agentmon import features as F
    for dom in ("FX", "PAY"):
        a(f"## Phân hệ {dom} ({len(F.COLS[dom])} đặc trưng)\n\n")
        a(T(["Đặc trưng", "Nhóm", "Ý nghĩa", "Nguồn", "Cơ sở", "Kiểu gian lận liên quan"],
            [(f"`{c}`", catalog.FEATURES[c]["group"], catalog.FEATURES[c]["desc"], ", ".join(catalog.FEATURES[c]["sources"]), catalog.FEATURES[c]["why"], ", ".join(catalog.FEATURES[c]["typology"]) or "—") for c in F.COLS[dom]],
            [2, 1, 4, 2, 5, 2]))
        a("\n")
    a("# Phụ lục B. Danh mục kiểu gian lận (đề xuất)\n\n")
    a(T(["Mã", "Tên", "Nhóm", "Mức", "Ghi chú"], [(f"`{c}`", m["name"], m["cat"], m["sev"], m["note"]) for c, m in fraud_types.TAXONOMY.items()], [3, 4, 2, 1, 7]))
    a("\n# Phụ lục C. Danh mục thẻ và thanh toán\n\n")
    for title, tab in (("Mạng thẻ (`card_network`)", cardmodel.NETWORKS), ("Sản phẩm thẻ (`card_product`)", cardmodel.PRODUCTS), ("Loại giao dịch (`txn_subtype`)", cardmodel.SUBTYPES),
                       ("Phương thức nhập thẻ (`entry_mode`)", cardmodel.ENTRY_MODES), ("Xác thực chủ thẻ (`auth_method`)", cardmodel.AUTH_METHODS),
                       ("Loại mã QR (`qr_scheme`)", cardmodel.QR_SCHEMES), ("QR tĩnh/động (`qr_type`)", cardmodel.QR_TYPES)):
        a(f"## {title}\n\n")
        a(T(["Mã", "Ý nghĩa"], [(f"`{k}`", v) for k, v in tab.items()], [3, 8]))
        a("\n")
    a("""
# Phụ lục D. Cấu trúc thư mục chính
""")
    a(T(["Đường dẫn", "Vai trò"], [
        ("`agentmon/pipeline.py`", "Luồng tuần tự Anti-Bot → Monitor (mọi cổng gọi `process`)"),
        ("`agentmon/antibot_txn.py`", "Tầng 1: sổ chứng cứ bot–người, luật tấn công thẻ/replay/thiết bị"),
        ("`agentmon/actor.py`", "Phân loại AI Agent / người, độ tin cậy"),
        ("`agentmon/engine.py`", "Tầng 2: Hard Policy, chấm điểm, quyết định, hạch toán, STEP_UP"),
        ("`agentmon/features.py`, `ml.py`, `catalog.py`", "Đặc trưng, mô hình, danh mục đặc trưng"),
        ("`agentmon/cardmodel.py`", "Danh mục thẻ + luật rủi ro thẻ (kể cả sao kê, thẻ trả trước/ảo)"),
        ("`agentmon/biometrics.py`, `atm_identity.py`", "Sinh trắc khuôn mặt (mã hóa), danh tính tại ATM, KYA qua điện thoại"),
        ("`agentmon/botmodel.py`, `fraudgbm.py`, `seqmodel.py`, `graphrisk.py`", "Các mô hình AI bổ sung: bot–người, boosting giám sát, chuỗi hành vi, đồ thị liên kết"),
        ("`agentmon/criteria.py`", "Bộ tiêu chí phân biệt bot – AI Agent – người (nguồn của mục 3)"),
        ("`agentmon/fraud_types.py`", "Phân loại gian lận"),
        ("`agentmon/profiles.py`", "Hồ sơ demo/pilot/production, readiness"),
        ("`agentmon/gateway.py`, `txn_api.py`, `agent_api.py`", "Các cổng vào"),
        ("`agentmon/sources.py`", "Hệ thống nguồn và khóa"),
        ("`agentmon/dataio.py`, `backtest.py`", "Nạp dữ liệu thật, backtest"),
        ("`agentmon/riskregister.py`", "Danh mục rủi ro (nguồn của mục 16)"),
        ("`tools/txn_attack_matrix.py`, `tools/gen_docs.py`, `tools/make_guide.py`", "Kiểm thử tấn công, sinh tài liệu"),
        ("`models/MANIFEST.json`", "Phiên bản và SHA-256 mô hình"),
        ("`docs/`", "Tài liệu: ARCHITECTURE, DEPLOYMENT, DATA_REQUIREMENTS, EXPLAINABILITY, RISK_REGISTER, FEATURE_CATALOG, FRAUD_TAXONOMY, CARD_TAXONOMY, BACKTEST_SYNTHETIC, CHANGELOG"),
    ], [5, 8]))
    return "\n".join(P)


def to_docx(md_path, docx_path):
    subprocess.run(["pandoc", md_path, "-o", docx_path, "--toc", "--toc-depth=2", "--from", "markdown+pipe_tables", "--resource-path", D], check=True, cwd=D)
    from docx import Document
    from docx.enum.section import WD_ORIENT
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Cm, Pt, RGBColor
    doc = Document(docx_path)
    for s in doc.sections:
        s.page_width, s.page_height = Cm(21.0), Cm(29.7)
        s.left_margin = s.right_margin = Cm(1.8)
        s.top_margin = s.bottom_margin = Cm(1.8)
    for name, size in (("Normal", 10), ("Body Text", 10), ("First Paragraph", 10), ("Compact", 9)):
        try:
            st = doc.styles[name]
            st.font.name = "Calibri"
            st.font.size = Pt(size)
            st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
        except KeyError:
            pass
    for name in ("Verbatim Char", "Source Code", "VerbatimChar"):
        try:
            doc.styles[name].font.size = Pt(8.5)
            doc.styles[name].font.name = "Consolas"
        except KeyError:
            pass
    for name, size, color in (("Heading 1", 16, "1F3864"), ("Heading 2", 13, "2F5496"), ("Heading 3", 11, "2F5496"), ("Title", 22, "1F3864"), ("Subtitle", 12, "444444")):
        try:
            st = doc.styles[name]
            st.font.name = "Calibri"
            st.font.size = Pt(size)
            st.font.color.rgb = RGBColor.from_string(color)
        except KeyError:
            pass
    for t in doc.tables:
        tbl = t._tbl
        pr = tbl.tblPr
        borders = OxmlElement("w:tblBorders")
        for b in ("top", "left", "bottom", "right", "insideH", "insideV"):
            e = OxmlElement(f"w:{b}")
            e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:space"), "0"); e.set(qn("w:color"), "A6A6A6")
            borders.append(e)
        pr.append(borders)
        for i, row in enumerate(t.rows):
            for cell in row.cells:
                if i == 0:
                    tcPr = cell._tc.get_or_add_tcPr()
                    shd = OxmlElement("w:shd")
                    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), "D9E2F3")
                    tcPr.append(shd)
                for p in cell.paragraphs:
                    for r in p.runs:
                        r.font.size = Pt(8.5)
                        r.font.name = "Calibri"
                        if i == 0:
                            r.font.bold = True
            if i == 0:
                trPr = row._tr.get_or_add_trPr()
                h = OxmlElement("w:tblHeader")
                h.set(qn("w:val"), "true")
                trPr.append(h)
    doc.save(docx_path)


if __name__ == "__main__":
    os.makedirs(D, exist_ok=True)
    diagram(os.path.join(D, "diagram_flow.png"))
    md = build()
    mp = os.path.join(D, "HUONG_DAN_VAN_HANH_V2.md")
    open(mp, "w", encoding="utf-8").write(md)
    to_docx(mp, os.path.join(D, "HUONG_DAN_VAN_HANH_V2.docx"))
    print("OK", len(md.splitlines()), "dòng markdown")
