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
pytest tests -q                 # cần requirements-dev.txt – 186 test (gồm đa tiến trình)
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


## Phiên bản 1.1 – điểm mới
* **Kênh giao dịch thẻ mở rộng:** ATM (`ATM_WITHDRAWAL`), ví điện tử (`WALLET_PAYMENT`, cần `wallet_provider` + `device_id`), Digibank/Digibiz (`BILL_PAYMENT`, `QR_PAYMENT`, `ONLINE_PURCHASE` qua `channel_type`), cùng POS và E-commerce. Hạn mức mới: `atm_per_txn`, `atm_daily`, `qr_bill_per_txn`. Test Lab có 36 kịch bản (FX 11, thanh toán 25).
* **Phân loại gian lận vs bất thường:** `fraud_class` (`FRAUD_SUSPECTED / ANOMALY_UNCONFIRMED / NORMAL`) và `fraud_types` (19 kiểu) – `docs/FRAUD_TAXONOMY.md`. Lớp giải thích dựa trên luật, không đổi quyết định.
* **Giải trình/kiểm toán:** `details.trace` + `trace_hash` + API `GET /api/agent/actions/<id>/explain` – `docs/EXPLAINABILITY.md`.
* **Phiên bản hóa mô hình:** `models/MANIFEST.json` (version, SHA-256, chỉ số in-sample **và holdout**), `AGENTMON_MODEL_ARCHIVE=1` để lưu bản cũ.
* **Dữ liệu thật & backtest:** `python -m agentmon.backtest --csv <file> --domain PAY` – `docs/DATA_REQUIREMENTS.md`, mẫu CSV `docs/templates/`.
* **Danh mục đặc trưng:** `docs/FEATURE_CATALOG.md` (nguồn: `agentmon/catalog.py`; `python -m tools.gen_docs`).
* **Kiến trúc & đồng thời:** Anti-Bot (kênh `/api`) và Monitor (kênh `/agent-api`) là hai kênh độc lập dùng chung Lớp 0; FX + thanh toán dùng chung số dư, khóa liên tiến trình – `docs/ARCHITECTURE.md`.
* **Đóng gói:** `Dockerfile`, `docker-compose.yml`, `render.yaml`, `Procfile`, `.env.example`, CI – `docs/DEPLOYMENT.md`.
* Trả lời bộ câu hỏi TSC: `docs/TRA_LOI_TSC.md`. Lịch sử thay đổi: `docs/CHANGELOG.md`.

> Mô hình vẫn huấn luyện trên **dữ liệu tổng hợp**; chưa có bằng chứng hiệu quả trên dữ liệu thật (`docs/BACKTEST_SYNTHETIC.md` chỉ là kiểm tra hồi quy).


## Phiên bản 2.0 – điểm mới (luồng tuần tự Anti-Bot → AI Agent Monitor)
* **Một luồng duy nhất:** mọi giao dịch (FX, thẻ mọi loại, chuyển tiền, QR/hóa đơn, mua sắm online) đi qua **Anti-Bot cấp giao dịch** (`antibot_txn.py`) rồi mới tới Monitor; `pipeline.py` ép thứ tự – `docs/ARCHITECTURE.md`.
* **Phân biệt bot thật và người:** sổ chứng cứ bot–người, bảng điều kiện công khai; Agent hợp lệ không bị phạt vì tự động hóa.
* **Phân biệt AI Agent và người ở Monitor:** `actor.py` (độ tin cậy, AGENT_ECHO, ACTOR_UNVERIFIED).
* **Mô hình thẻ đầy đủ:** Visa, Mastercard, JCB, UnionPay, Amex, Discover/Diners, NAPAS; credit/debit/prepaid/virtual/corporate; mua, pre-auth, capture, refund, reversal, cash advance, recurring, MOTO, trả góp…; chip/NFC/từ/nhập tay/ECOM/ví/QR – `docs/CARD_TAXONOMY.md`.
* **Hồ sơ demo/pilot/production + cổng sẵn sàng:** `profiles.py`, `GET /api/agent/hq/readiness`.
* **Danh mục 63 rủi ro** cần tránh (demo/pilot vs production) – `docs/RISK_REGISTER.md`.
* **Tối ưu:** trigger số tiền lớn chỉ áp khi lệch thói quen → báo nhầm giảm ~22% tương đối trên dữ liệu tổng hợp (recall gần như không đổi).
* Kiểm thử: `pytest` (186 test), `python -m tools.txn_attack_matrix` (13 kịch bản tấn công giao dịch).
* **Hướng dẫn chi tiết (Word):** `HUONG_DAN_VAN_HANH_V2.docx` đi kèm gói.


## Phiên bản 2.1 – điểm mới
* **Camera AI tại ATM (KYC/KYA):** nhận diện chính chủ / người khác / không có người / giả mạo; xác nhận qua điện thoại khi chưa chắc chắn – `docs/HUONG_DAN_VAN_HANH_V2.docx` (chương 7).
* **Bộ tiêu chí phân biệt bot – AI Agent – người:** `docs/CRITERIA.md` (24 tiêu chí, nguồn `agentmon/criteria.py`).
* **Nhiều mô hình AI:** Isolation Forest + gradient boosting + mô hình bot–người + chuỗi hành vi + đồ thị liên kết + Face-AI + LLM Critic; chế độ active/shadow (`ENSEMBLE_MODE`).
* **Thẻ đầy đủ hơn:** thanh toán sao kê thẻ tín dụng, thẻ trả trước, ATM, ví, QR/hóa đơn, mọi mạng thẻ; ma trận phân biệt giao dịch thật/đáng ngờ (chương 8.6).
* Huấn luyện toàn bộ: `python -m agentmon.train_cli`. Kiểm thử: `pytest` và `python -m tools.txn_attack_matrix` (18 kịch bản).
