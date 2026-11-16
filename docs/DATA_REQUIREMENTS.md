# Yêu cầu dữ liệu thật để huấn luyện/kiểm chứng

Mô hình hiện chạy trên **dữ liệu tổng hợp**. Để có số liệu hiệu quả đáng tin, cần dữ liệu thật theo đặc tả dưới đây.
Công cụ: `python -m agentmon.backtest --csv <file> --domain PAY|FX [--save-model]`. File mẫu: `docs/templates/`.

## 1. Khối lượng và thời gian
| Hạng mục | Tối thiểu | Khuyến nghị |
|---|---|---|
| Khoảng thời gian | 6 tháng | ≥ 12 tháng (bắt được tính mùa vụ, chargeback chậm 60–120 ngày) |
| Số giao dịch mỗi phân hệ | vài nghìn (công cụ từ chối < 500 dòng) | ≥ 500.000 |
| Số khách | ≥ 200 | ≥ 5.000 |
| Nhãn gian lận dương tính | ≥ 30 (dưới ngưỡng này kết quả không ổn định) | ≥ 300 |

## 2. Nguồn dữ liệu đề xuất (cần Khối CNTT/Vận hành xác nhận hệ thống cụ thể)
| Dữ liệu | Hệ thống nguồn (đề xuất) | Cột |
|---|---|---|
| Giao dịch chuyển tiền | Core banking / IPS | `amount_vnd, beneficiary_account` |
| Giao dịch thẻ POS/CNP/ATM | Card switch / Card management | `amount_vnd, merchant_id, mcc, country, three_ds, channel_type` |
| Ví điện tử | Token service provider (Apple/Google Pay) | `channel_type=WALLET, device_id` |
| Digibank/Digibiz | Log kênh số | `channel_type=DIGIBANK/DIGIBIZ` |
| Lệnh FX | Hệ thống giao dịch FX | `pair, side, notional_usd, leverage` |
| Số dư, phân khúc | Core banking / CIF | `balance_vnd, segment` |
| **Nhãn gian lận** | Hệ thống quản lý vụ việc gian lận, chargeback, khiếu nại khách | `fraud_label, label_source` |

## 3. Định nghĩa nhãn (`fraud_label`, `label_source`)
* `1` = giao dịch được **xác nhận** gian lận; `0` = xác nhận hợp lệ; **để trống** = chưa biết (coi là 0 khi đánh giá nhưng không dùng nhãn để học).
* `label_source` ∈ `chargeback | fraud_case | customer_dispute | kya_denied | review_rejected`.
  Lưu ý: `kya_denied`/`review_rejected` là nhãn **yếu** (khách từ chối ≠ chắc chắn gian lận) – nên báo cáo tách riêng.
* Chỉ dùng nhãn đã "chín" (đủ thời gian chargeback) để tránh nhãn trễ làm sai số.

## 4. Cách đánh giá (đã cài trong `agentmon/backtest.py`)
1. **Tách theo thời gian** (train 70% đầu → test 30% sau), không trộn ngẫu nhiên, để mô phỏng đúng việc triển khai về tương lai.
2. Huấn luyện **chỉ trên giao dịch không có nhãn gian lận** của quá khứ (Isolation Forest không giám sát).
3. Chỉ số: AUC/AP của điểm ML và điểm cuối; tại ngưỡng KYA/REVIEW/BLOCK: tỷ lệ cảnh báo, recall, precision, FPR; **trigger nào gây báo nhầm** (để hiệu chỉnh chính sách).
4. Tiêu chí chấp nhận do ngân hàng đặt, ví dụ: recall ≥ x% ở mức REVIEW, tỷ lệ KYA ≤ y% giao dịch lành tính, precision BLOCK ≥ z%.
5. Hiệu chỉnh lại ngưỡng (`kya/review/block_threshold`) và `kya_above` theo kết quả; huấn luyện lại bằng `--save-model` (ghi version + SHA-256 vào `models/MANIFEST.json`).

## 5. Bảo mật dữ liệu
Che/mã hóa PAN (chỉ cần token), băm số tài khoản nếu có thể, không đưa CVV/PIN. Tệp CSV chỉ lưu trong môi trường được phê duyệt, xóa sau khi huấn luyện nếu chính sách yêu cầu.

## 6. Việc cần Ngân hàng cung cấp
Hệ thống nguồn và đầu mối dữ liệu; khoảng thời gian và khối lượng thực tế; định nghĩa nhãn chuẩn; tiêu chí chấp nhận (mục 4.4).
