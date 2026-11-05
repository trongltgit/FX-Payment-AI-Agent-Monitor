# Anti-Bot Pro + AI Agent Monitor (FX & Thanh toán) – hệ thống hợp nhất

Một hệ thống duy nhất: trang đăng nhập chung, 3 cổng **TSC / Chi nhánh / Khách hàng** (cấu hình phân cấp như Anti-Bot),
mỗi cổng có thêm các tab **AI Agent Monitor** cho 2 phân hệ tách biệt:

* **FX Trading** – kiểm soát hạn mức và hành vi giao dịch FX của Agent.
* **Thanh toán** – kiểm soát hạn mức và hành vi chuyển tiền, mua sắm online, thanh toán thẻ **Visa / Mastercard** (tuân thủ số thẻ kiểu PCI-DSS).

Pipeline: `Hard Policy → Feature Engineering → Isolation Forest → LLM Critic (Groq) → ALLOW | KYA | REVIEW | BLOCK → CSDL`.
Giao dịch bất thường (vd. khách chưa từng giao dịch online bỗng giao dịch) được gửi **KYA qua ứng dụng Authenticator** để khách duyệt trước khi thực hiện.
Khách hàng phải **đăng ký Agent với ngân hàng** (điều khoản pháp lý + chi nhánh duyệt) thì Agent mới được giao dịch.

> Đọc **docs/HUONG_DAN_VAN_HANH.pdf** để biết nguyên tắc và cách vận hành chi tiết.

## Chạy nhanh
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # đặt SECRET_KEY >= 32 ký tự
python app.py                   # http://127.0.0.1:5000  (lần đầu tự tạo CSDL + dữ liệu demo)
pytest tests -q                 # cần requirements-dev.txt – 82 test
```
Windows PowerShell: `py -m venv .venv; .\.venv\Scripts\Activate.ps1`.

## Tài khoản demo (mật khẩu `demo123`)
| Cổng | Tài khoản |
|---|---|
| TSC | `hq01` |
| Chi nhánh | `admin_cn01` (CN001), `admin_cn02` (CN002), `staff01..03` |
| Khách hàng | `cust001` (VIP), `cust002` (doanh nghiệp), `cust003` (ngủ đông), `cust004` (chưa từng online, Agent chờ duyệt), `cust005` (VIP đòn bẩy cao) |

Ứng dụng Authenticator giả lập (điện thoại): `/authenticator`.

## Thử nhanh
1. `cust001` → tab **Test Lab** → chạy `FX-02`, `PAY-08` (BLOCK), `FX-06` (KYA).
2. Tab **Authenticator & KYA** → nhập OTP (demo hiển thị sẵn) → **Duyệt** → giao dịch EXECUTED trong **Monitor FX**.
3. `cust004` → Authenticator → đăng ký Agent; `admin_cn01` → **Duyệt Agent**; `cust004` cấp API key và gọi
   `POST /agent-api/v1/monitor/action` (xem PDF mục 11).
4. `hq01` → **Agent & Kill-switch** → bật kill-switch, chạy lại `FX-01` → BLOCK.

## LLM Critic (Groq)
Đặt trong `.env`: `LLM_PROVIDER=groq`, `GROQ_API_KEY=...`. Không đặt = bộ phản biện luật (hệ thống vẫn chạy đầy đủ).

## Cấu trúc
`app/` Anti-Bot gốc · `agentmon/` module AI Agent Monitor · `templates/`, `static/` giao diện · `models/` Isolation Forest ·
`tests/` · `tools/make_manual.py` sinh lại PDF · `docs/`.

## Lưu ý
Bản demo/pilot: SQLite, số dư mô phỏng, số thẻ test, dữ liệu huấn luyện ML tổng hợp, danh sách cấm vận mẫu.
Xem mục 15 của PDF để biết các việc cần làm trước khi dùng dữ liệu thật.
