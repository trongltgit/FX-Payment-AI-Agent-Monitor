# Changelog

## 2.1.0
**Thêm**
- **Danh tính tại ATM bằng camera AI** (`biometrics.py`, `atm_identity.py`): đăng ký khuôn mặt có đồng ý (embedding mã hóa, không lưu ảnh), so khớp, liveness/injection (PAD), nhiều khuôn mặt, camera bị che/hỏng, chưa đăng ký; kết luận *chính chủ / người khác / không có người / giả mạo*; **KYA qua điện thoại chủ thẻ (APP_CONFIRM)** khi chưa chắc chắn; tín hiệu nhịp PIN, PIN sai, thu gom thẻ trên một ATM; AI Agent rút ATM → bắt buộc chủ thẻ xác nhận (`AGENT_CASH_OUT`). Tầng 1 chặn giả mạo sinh trắc và giao dịch ATM không có người.
- **Bộ nhiều mô hình AI:** mô hình bot–người (gradient boosting, Tầng 1, `botmodel.py`), gradient boosting giám sát làm ý kiến thứ hai (`fraudgbm.py`), mô hình chuỗi hành vi Markov (`seqmodel.py`), đồ thị liên kết thiết bị/người nhận/IP (`graphrisk.py`); chế độ `active`/`shadow` (`ENSEMBLE_MODE`, mặc định pilot/production = shadow); chỉ được NÂNG cảnh báo.
- **Thanh toán dư nợ sao kê thẻ tín dụng** (`CARD_STATEMENT_PAYMENT`) + luật trả thừa, người lạ trả hộ, thẻ tín dụng trả thẻ tín dụng; luật thẻ trả trước.
- **Bộ tiêu chí phân biệt bot – AI Agent – người** (`criteria.py`, 24 tiêu chí) và 9 rủi ro mới (nhóm K) – danh mục rủi ro 63 mục.
- Kịch bản kiểm thử: 14 kịch bản người dùng (`lab.HUMAN_SCEN`), ma trận tấn công 18 kịch bản (thêm 6 kịch bản ATM + khuôn mặt); `tests/test_v21.py`.
- Readiness: `AI_ENSEMBLE_REAL_DATA`, `AI_ENSEMBLE_SHADOW`, `FACE_AI_PROVIDER`.
**Đổi**
- Test Lab PAY-17: AI Agent rút ATM nay cần KYA (trước đây ALLOW). `NO_PERSON_AT_ATM` là luật chặn cứng ở Tầng 1 (ATM không thể thử thách bằng Turnstile).
- Bộ dữ liệu huấn luyện mô hình bot–người được làm khó hơn (bản đầu AUC = 1,0 do quá dễ nên bị loại).
**Sửa**
- Test Lab tạo số tài khoản bằng `str(store.now())[-5:]` có thể chứa dấu chấm gây lỗi ngẫu nhiên (lỗi có từ bản gốc).
**Giới hạn đã biết**
- Face-AI chỉ giả lập; chưa tích hợp camera/nhà cung cấp thật; boosting giám sát và mô hình bot–người học trên nhãn tổng hợp (vòng tròn) nên chạy shadow ở pilot/production.

## 2.0.0
**Thêm**
- Luồng tuần tự bắt buộc **Anti-Bot (tầng 1) → AI Agent Monitor (tầng 2)** cho mọi giao dịch: `pipeline.py`, `antibot_txn.py`, `actor.py`; cổng thống nhất `POST /gateway/v2/transaction`; agent-api và txn-api nay đi qua pipeline.
- Anti-Bot cấp giao dịch: phân loại HUMAN_VERIFIED / HUMAN_LIKELY / AUTOMATION_AUTHORIZED / SUSPECT / MALICIOUS_BOT; luật replay, dấu thời gian, dò BIN, card testing, bão từ chối, trang trại thiết bị, nhịp metronome, khóa Agent bị người dùng; bảng `antibot_events`.
- Phân loại người thực hiện ở Monitor (độ tin cậy, AGENT_ECHO, `ACTOR_UNVERIFIED`, kiểu gian lận `ACTOR_SPOOFING`).
- Mô hình thẻ `cardmodel.py`: mạng thẻ, sản phẩm, loại giao dịch, entry mode, xác thực, QR; 10 luật thẻ (nhập tay, fallback, chạm không CVM, hoàn tiền, capture vượt pre-auth, thẻ NAPAS ở nước ngoài, QR tĩnh, di chuyển bất khả thi…).
- Hồ sơ triển khai và kiểm tra sẵn sàng `profiles.py`; danh mục rủi ro `riskregister.py` (54 mục); `tools/txn_attack_matrix.py`.
**Đổi**
- Trigger `AMOUNT_OVER_KYA` chỉ áp khi số tiền lệch thói quen (`kya_above_min_ratio`, mặc định 1,5): báo nhầm 0,152 → 0,119, precision 0,555 → 0,612, recall 0,815 → 0,811 (tập test tổng hợp, phân hệ thanh toán).
- `PRICING_ENVIRONMENT=production` được hiểu là hồ sơ pilot; hồ sơ production phải đặt rõ `DEPLOY_PROFILE=production`.
- Tín hiệu phiên (`session.*`) được kiểm tra kiểu và khoảng giá trị (sai → 400).
**Giới hạn đã biết**
- Mô hình vẫn huấn luyện trên dữ liệu tổng hợp; CSDL SQLite; dữ liệu khách/thẻ mô phỏng; luật thẻ là luật theo thông lệ chưa hiệu chỉnh trên dữ liệu thật.

## 1.1.0
**Thêm**
- Kênh thẻ: ATM, ví điện tử, Digibank/Digibiz (hóa đơn, QR); `channel_type`, `device_id`, `wallet_provider`; 6 đặc trưng PAY mới (PAY 31 → 37); hạn mức `atm_per_txn`, `atm_daily`, `qr_bill_per_txn`; trigger `NEW_DEVICE`, `ATM_FOREIGN`.
- `fraud_types.py` (19 kiểu gian lận, phân loại FRAUD_SUSPECTED / ANOMALY_UNCONFIRMED / NORMAL), `catalog.py` (danh mục đặc trưng).
- Trace giải trình + `trace_hash` + API explain; cột `fraud_class, fraud_types, model_version, trace_hash, channel_type, device_id` (tự migrate CSDL cũ).
- Phiên bản hóa mô hình, MANIFEST, kiểm tra toàn vẹn SHA-256, đánh giá holdout khi huấn luyện.
- `dataio.py`, `backtest.py`, mẫu CSV; tín hiệu chéo FX↔thanh toán (`cross_n5`, `CROSS_DOMAIN_BURST`).
- Đóng gói: Dockerfile, compose, render.yaml, Procfile, .env.example, Makefile, CI. Test Lab 27 → 36 kịch bản; test 82 → 102.
**Sửa**
- Khóa đánh giá/hạch toán trước đây chỉ có tác dụng trong 1 tiến trình → thêm khóa tệp liên tiến trình (an toàn khi gunicorn nhiều worker).
- Công thức điểm cuối gom về `features.blend()` (một nguồn duy nhất cho engine, huấn luyện, backtest).
- Mô hình FX nặng 22 MB (huấn luyện cũ) → ~350 KB (256 mẫu/cây, nén).
- Agent gửi API key sai nhiều lần nay đẩy `ip_strike` sang Anti-Bot.
**Phát hiện khi đánh giá (chưa xử lý, cần hiệu chỉnh trên dữ liệu thật)**
- Trên dữ liệu tổng hợp tập tách riêng, trigger `AMOUNT_OVER_KYA` và `NEW_BENEFICIARY` làm tỷ lệ KYA phân hệ thanh toán ≈ 32% (FPR ≈ 21%) do ngưỡng `kya_above` cố định theo phân khúc; cần hiệu chỉnh theo dữ liệu thật.
- Hard policy chưa kiểm tra "ví đã bật cho thẻ" (không có cờ ví trên thẻ).
