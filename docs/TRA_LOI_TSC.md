---
title: "Trả lời bộ câu hỏi TSC – AI Agent Monitor (phiên bản 1.1)"
---

*Số liệu lấy từ mã nguồn và kết quả chạy thực tế của bản 1.1 (102 test đạt). Chỗ nào hệ thống chưa làm được hoặc chưa kiểm chứng trên dữ liệu thật được ghi rõ.*

## 1. Phương pháp mô hình
Mô hình lõi là **Isolation Forest** (học không giám sát) – hai mô hình riêng: FX (21 đặc trưng) và Thanh toán (37 đặc trưng); 150 cây, 256 mẫu/cây, `contamination = 0,08`. Không dùng học có giám sát (XGBoost, Logistic Regression) vì chưa có nhãn gian lận thật.

ML chỉ là một thành phần của quy trình quyết định: **Hard Policy** (chặn cứng, không bị ghi đè) → điểm **ML + Hành vi + Velocity** → **Trigger KYA** → **LLM Critic** (chỉ được nâng mức) → ALLOW / KYA / REVIEW / BLOCK.
Điểm cuối: `final = 0,70 × (0,40·ML + 0,30·Hành vi + 0,30·Velocity) + 0,30 × max(Hành vi, Velocity)` (ML đơn độc không kéo điểm lên được; cần tín hiệu hành vi hoặc velocity đồng thuận).

## 2. Giám sát giao dịch của Agent hay của khách hàng?
Chỉ giao dịch do **AI Agent** gửi qua `/agent-api/v1/monitor/action`. Giao dịch người dùng tự thao tác trên portal **không** do Monitor chấm điểm; riêng báo giá/lệnh FX của người dùng được **Anti-Bot** bảo vệ (câu 12). Lịch sử giao dịch của khách chỉ dùng làm baseline thói quen.

## 3. Đã hoàn thiện code và đóng gói chưa?
Đã hoàn thiện ở mức **pilot có thể chạy**: mã nguồn, 102 test (gồm kiểm thử hai tiến trình đồng thời), mô hình có phiên bản + SHA-256, `Dockerfile`, `docker-compose.yml`, `render.yaml`, `Procfile`, `.env.example`, CI, tài liệu (`docs/`).
**Chưa phải production:** CSDL SQLite, dữ liệu khách/thẻ là mô phỏng (`mock_db`), chưa tích hợp core banking/switch thẻ/HSM, chưa test tải, chưa pentest độc lập, mô hình chưa huấn luyện trên dữ liệu thật (bảng điều kiện ở `docs/DEPLOYMENT.md`).
Lưu ý: `tools/security_smoke.py` (45 kiểm tra) được tài liệu vận hành cũ nhắc tới **không có trong gói**; kiểm thử bảo mật hiện nằm ở `tests/` và `tools/attack_matrix.py`.

## 4. Dữ liệu kiểm thử và cơ sở đánh giá
Toàn bộ dữ liệu hiện là **tổng hợp**: bộ sinh `ml.generate()` (45 persona × 170 giao dịch mỗi phân hệ, 8% bất thường chèn vào), dữ liệu demo `seed.py`, 36 kịch bản Test Lab (FX 11, thanh toán 25), 102 test tự động.

Từ bản 1.1, mỗi lần huấn luyện còn đánh giá trên **tập tách riêng** (khác seed, khác khách). Kết quả trên dữ liệu tổng hợp (`docs/BACKTEST_SYNTHETIC.md`):

| Phân hệ | AUC điểm cuối | Cảnh báo KYA trở lên | Recall | Precision | Báo nhầm (FPR) |
|---|---|---|---|---|---|
| Thanh toán | 0,946 | 34,7% giao dịch | 0,83 | 0,50 | 0,22 |
| FX | 0,872 | 10,7% giao dịch | 0,38 | 0,72 | 0,04 |

**Cần nói rõ:** đây chỉ là kiểm tra hồi quy trên dữ liệu do chính hệ thống sinh ra, **không phải bằng chứng hiệu quả thực tế**. Phát hiện đáng chú ý: ở phân hệ thanh toán, trigger `AMOUNT_OVER_KYA` và `NEW_BENEFICIARY` gây phần lớn cảnh báo KYA cho giao dịch lành tính – cần hiệu chỉnh `kya_above` theo dữ liệu thật. Công cụ đánh giá trên dữ liệu thật đã sẵn sàng (`python -m agentmon.backtest --csv …`, đặc tả ở `docs/DATA_REQUIREMENTS.md`).

## 5. Cơ sở xây dựng feature và nguồn dữ liệu
Đặc trưng được thiết kế theo **kinh nghiệm nghiệp vụ và các kiểu gian lận đã biết**, chia nhóm: lệch so với thói quen của chính khách, tốc độ/nhịp gửi lệnh, mức dùng hạn mức/số dư, ngữ cảnh (merchant, quốc gia, kênh, thiết bị) và đặc trưng gắn với kiểu gian lận. **Chưa** được chọn/kiểm chứng bằng nhãn gian lận thật.
Danh mục đầy đủ (ý nghĩa, nguồn, cơ sở, kiểu gian lận liên quan cho từng đặc trưng): `docs/FEATURE_CATALOG.md`.
Nguồn dữ liệu: lịch sử giao dịch đã thực hiện của khách (tối đa 365 ngày/600 giao dịch), các lần Agent gửi lệnh 24 giờ gần nhất, payload hiện tại, số dư khả dụng, hạn mức hiệu lực MIN(TSC, Chi nhánh, Agent) và danh mục MCC/quốc gia, cờ suspicion, thiết bị ví đã dùng. Hiện tất cả là mô phỏng; khi lên thật lấy từ core banking, switch thẻ, token service, log Digibank/Digibiz.

## 6. Bắt buộc đăng ký Agent: chỉ FX hay cả giao dịch khác?
Áp dụng cho **mọi nghiệp vụ Agent thực hiện**: FX, chuyển tiền, mua sắm online, thẻ POS, ATM, ví, hóa đơn, QR. Agent chưa đăng ký hoặc chưa được chi nhánh duyệt bị **BLOCK** hoàn toàn (kịch bản FX-11, PAY-15). Không áp dụng cho giao dịch người dùng tự thao tác.

## 7. Phân biệt gian lận và bất thường
Từ bản 1.1 hệ thống có **lớp phân loại** (dựa trên luật, không đổi quyết định):

* `FRAUD_SUSPECTED` – có dấu hiệu gian lận (ít nhất một dấu hiệu mức HIGH hoặc ≥ 2 dấu hiệu MED), kèm loại gian lận và bằng chứng;
* `ANOMALY_UNCONFIRMED` – bất thường có thể hợp lệ (lần đầu online, tài khoản ngủ đông, người nhận mới…), xử lý bằng **KYA** (khách xác minh);
* `NORMAL`.

Danh mục 19 kiểu (`docs/FRAUD_TAXONOMY.md`): dò thẻ, cờ bạc, thanh toán khống/ĐVCNT nghi vấn, né hạn mức, chiếm quyền tài khoản, rút cạn số dư/tài khoản trung gian, CNP không xác thực, lộ dữ liệu thẻ, quốc gia cấm vận/danh sách chặn, lạm dụng ví trên thiết bị lạ, rút ATM nước ngoài, dồn lệnh FX, lạm dụng đòn bẩy, FX + thanh toán dồn dập…
**Giới hạn:** danh mục là **đề xuất theo thông lệ ngành**, cần đối chiếu với danh mục chuẩn của khối phòng chống gian lận; "thanh toán khống" mới là heuristic, cần dữ liệu rủi ro đơn vị chấp nhận thẻ; chưa hiệu chỉnh trên nhãn thật; chưa có vòng phản hồi nhãn (ví dụ khách từ chối KYA chưa được dùng để học lại).

## 8. Có lưu giải thích kết quả tính điểm không?
**Có, đầy đủ để tái lập** (`docs/EXPLAINABILITY.md`). Mỗi quyết định lưu: điểm ML/hành vi/velocity/cuối, lý do, trigger, nhận xét LLM, phân loại gian lận, **phiên bản + SHA-256 mô hình**, **ngưỡng và trọng số tại thời điểm quyết định**, **vector đặc trưng**, baseline khách, hạn mức hiệu lực, **đường quyết định** từng bước, và `trace_hash` (SHA-256, phát hiện sửa đổi). Nhân viên/TSC xem qua `GET /api/agent/actions/<id>/explain` (kèm kiểm tra toàn vẹn); khách chỉ thấy lý do công khai. Không lưu PAN/CVV. Bản ghi tạo trước v1.1 không có trace.

## 9. Phạm vi Anti-Bot
Kênh `/api/*` (người dùng): đăng nhập, phiên, báo giá/lệnh FX (chấm điểm hành vi bot). Lớp 0 (ban IP, honeypot) áp dụng cho cả `/agent-api`. **Anti-Bot không chấm điểm giao dịch thanh toán thẻ.**

## 10. Phạm vi AI Agent Monitor
Cả **FX và Thanh toán** (hai phân hệ, hai mô hình), chỉ cho giao dịch do Agent khởi tạo.

## 11. Các loại giao dịch thẻ được đánh giá

| Loại | Trạng thái (bản 1.1) | `kind` / `channel_type` |
|---|---|---|
| E-commerce (website ĐVCNT) | Có | `ONLINE_PURCHASE` / `CNP` (cờ 3DS) |
| Thẻ tại POS | Có, kênh riêng; **chưa** có đặc trưng EMV/contactless/terminal | `CARD_PAYMENT` / `POS` |
| ATM | **Mới** – hạn mức lần/ngày, ATM nước ngoài, ngoài giờ | `ATM_WITHDRAWAL` / `ATM` |
| Ví điện tử (Apple/Google/Samsung Pay) | **Mới** – theo dõi thiết bị mới; **chưa** có cờ "thẻ đã bật ví" và chưa kiểm tra token DPAN | `WALLET_PAYMENT` / `WALLET` |
| Digibank/Digibiz | **Mới** – hóa đơn, QR, mua sắm, chuyển tiền qua kênh số | `BILL_PAYMENT`, `QR_PAYMENT`, `ONLINE_PURCHASE`, `TRANSFER` / `DIGIBANK`, `DIGIBIZ` |

Các kênh mới đã có kịch bản Test Lab (PAY-17…PAY-25) và test tự động. Baseline của kênh mới dựa trên dữ liệu demo; cần dữ liệu thật để hiệu chỉnh.

## 12. Mô hình đi qua Anti-Bot rồi Agent Monitor tuần tự, hay song song?
**Không tuần tự và không cùng một request:** hai **kênh độc lập**, chung **Lớp 0** (ban IP, honeypot, audit, Redis). Người dùng đi `/api/*` → Anti-Bot; Agent đi `/agent-api/v1/*` → Monitor. Một giao dịch chỉ đi một kênh. Monitor đẩy tín hiệu ngược sang Anti-Bot (API key sai nhiều lần → ban IP chung). Sơ đồ và hệ quả: `docs/ARCHITECTURE.md`.
**Cần quyết định nghiệp vụ:** có hợp nhất để Monitor cũng chấm điểm giao dịch người dùng trên portal không.

## 13. FX và thanh toán (settlement) xảy ra cùng lúc thì sao?
* Cùng một engine, hai mô hình và hạn mức riêng; **dùng chung số dư**: FX giữ ký quỹ `notional/đòn bẩy`, thanh toán giữ toàn bộ số tiền; lệnh chờ KYA/REVIEW giữ chỗ nên hai lệnh đồng thời không thể dùng chung một khoản tiền.
* Kiểm tra số dư/hạn mức rồi ghi là **nguyên tử giữa các tiến trình** (khóa tệp). Đã kiểm chứng bằng hai tiến trình đồng thời (số dư 30 triệu, mỗi lệnh 28 triệu): luôn đúng một lệnh giữ được số dư, số dư không âm. Khi chạy **nhiều máy** cần PostgreSQL + advisory lock (chưa có).
* Velocity tính theo Agent xuyên phân hệ; thêm tín hiệu `cross_n5` (≥ 4 lệnh ở phân hệ kia trong 5 phút) → tăng điểm và gán `CROSS_DOMAIN_BURST`.
* Hạn mức FX (USD) và thanh toán (VND) tính riêng, không cộng gộp.
