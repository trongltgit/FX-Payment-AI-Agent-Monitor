# Danh mục kiểu gian lận (Fraud Typology)

Sinh tự động từ `agentmon/fraud_types.py`. **Đây là danh mục đề xuất** – cần đối chiếu với danh mục chuẩn của khối phòng chống gian lận.

| Mã | Tên | Nhóm | Mức | Ghi chú |
|---|---|---|---|---|
| `CARD_TESTING` | Dò thẻ (card testing) | CARD_FRAUD | HIGH | Chuỗi giao dịch giá trị rất nhỏ/nhiều merchant để kiểm tra thẻ còn hiệu lực. |
| `ILLEGAL_GAMBLING` | Cờ bạc / cá cược | POLICY_AML | HIGH | MCC thuộc nhóm cờ bạc (7995…). Chặn cứng theo chính sách TSC. |
| `QUASI_CASH_CRYPTO` | Quasi-cash / tiền mã hóa / ví lưu giá trị | POLICY_AML | MED | MCC 6051, 6540 – kênh chuyển giá trị khó truy vết. |
| `FICTITIOUS_PAYMENT` | Thanh toán khống / ĐVCNT nghi vấn | MERCHANT_FRAUD | MED | Heuristic: merchant mới + số tiền lớn/tròn + MCC rủi ro/không 3DS, hoặc lặp lại cùng merchant mới. CẦN dữ liệu rủi ro ĐVCNT (MID, ngày onboard, chargeback) để chính xác. |
| `STRUCTURING` | Tách nhỏ / né hạn mức (structuring) | AML | MED | Số tiền sát trần hạn mức. |
| `ACCOUNT_TAKEOVER` | Chiếm quyền tài khoản / thông tin xác thực | ATO | HIGH | Khách ít/chưa dùng kênh online hoặc ngủ đông + (người nhận/thiết bị/quốc gia mới hoặc rút cạn số dư). |
| `FUND_DRAIN_MULE` | Rút cạn số dư / tài khoản trung gian (mule) | ATO_AML | HIGH | Dùng ≥ 70% số dư chuyển cho người nhận mới. |
| `CNP_NO_AUTH` | Gian lận thẻ CNP không xác thực | CARD_FRAUD | MED | CNP vượt ngưỡng nhưng không có 3-D Secure. |
| `PCI_EXPOSURE` | Lộ dữ liệu thẻ (PAN/CVV trong payload) | DATA_SECURITY | HIGH | Agent gửi số thẻ/CVV – vi phạm PCI-DSS; dữ liệu đã được che. |
| `SANCTIONS_BLOCKLIST` | Quốc gia cấm vận / tài khoản trong danh sách chặn | SANCTIONS | HIGH | Theo danh sách TSC cấu hình. |
| `HIGH_RISK_GEO` | Quốc gia rủi ro cao | CARD_FRAUD | MED | Theo danh sách TSC cấu hình. |
| `HIGH_RISK_MCC` | Ngành hàng rủi ro cao | CARD_FRAUD | MED | Theo danh sách TSC cấu hình. |
| `WALLET_DEVICE_ABUSE` | Lạm dụng ví điện tử trên thiết bị lạ | WALLET_FRAUD | MED | Thẻ thanh toán qua ví trên thiết bị chưa từng dùng; nâng HIGH nếu số tiền bất thường. |
| `ATM_CASHOUT_ABROAD` | Rút tiền ATM nước ngoài (cash-out) | CARD_FRAUD | MED | ATM ngoài VN; nâng HIGH nếu ngoài giờ hoặc số tiền bất thường. |
| `FX_BOT_BURST` | Dồn lệnh FX tự động bất thường | AGENT_ABUSE | MED | Nhiều lệnh/5 phút hoặc nhịp đều như máy. |
| `FX_LEVERAGE_ABUSE` | Lạm dụng đòn bẩy FX | AGENT_ABUSE | MED | Đòn bẩy tăng đột biến so với thói quen. |
| `OFFHOUR_LARGE` | Giao dịch lớn ngoài giờ | ATO | MED | Gấp > 3 lần thường lệ trong khung 23h–5h. |
| `CROSS_DOMAIN_BURST` | FX và thanh toán dồn dập đồng thời | AGENT_ABUSE | MED | ≥ 4 lệnh ở phân hệ khác trong 5 phút: nghi Agent bị điều khiển hoặc rút tiền ngay sau khi giao dịch FX. |
| `SESSION_BOT` | Phiên người dùng có dấu hiệu bot/tự động | ATO | MED | Điểm Anti-Bot của phiên ≥ 70/100; nâng HIGH khi ≥ 90 hoặc kèm thiết bị/người nhận mới. |
| `MULE_COLLECTION` | Tài khoản trung gian / thu gom tiền (mule) | ATO_AML | MED | ≥ 3 khách khác chuyển tới cùng người nhận trong 24 giờ; HIGH khi ≥ 5. |
| `ACTOR_CONFLICT` | Người và Agent cùng thao tác dồn dập | AGENT_ABUSE | MED | ≥ 3 giao dịch của loại người thực hiện ngược lại trong 10 phút trên cùng tài khoản. |
| `CARD_MANUAL_ENTRY` | Nhập tay số thẻ / MOTO | CARD_FRAUD | MED | Giao dịch không xuất trình thẻ vật lý; rủi ro dùng số thẻ bị lộ. |
| `CARD_SKIMMING` | Thẻ giả / skimming / chạm không xác thực | CARD_FRAUD | MED | Fallback quẹt từ, chạm vượt hạn mức không CVM, thẻ nội địa dùng nước ngoài. |
| `REFUND_ABUSE` | Lạm dụng hoàn tiền | MERCHANT_FRAUD | MED | Hoàn tiền không có giao dịch gốc hoặc về thẻ khác; HIGH khi về thẻ khác. |
| `CARD_MERCHANT_ABUSE` | Merchant lạm dụng capture/pre-auth | MERCHANT_FRAUD | MED | Capture vượt 120% số tiền pre-auth. |
| `QR_SWAP` | Thay/giả mã QR tĩnh | QR_FRAUD | MED | QR tĩnh số tiền lớn tới merchant lạ. |
| `IMPOSSIBLE_TRAVEL` | Di chuyển bất khả thi | CARD_FRAUD | HIGH | Hai giao dịch ở hai quốc gia khác nhau cách nhau < 2 giờ. |
| `ACTOR_SPOOFING` | Khai báo người thực hiện không khớp quan sát | AGENT_ABUSE | MED | Khai báo là người nhưng hành vi tự động (hoặc ngược lại); khóa Agent bị người dùng chung. |
| `ATM_THIRD_PARTY_USE` | Người khác dùng thẻ tại ATM (khuôn mặt không khớp) | CARD_FRAUD | HIGH | Camera AI: khuôn mặt không khớp mẫu đã đăng ký của chủ thẻ. |
| `ATM_SPOOF_ATTACK` | Giả mạo sinh trắc tại ATM (ảnh/video/mặt nạ/deepfake) | CARD_FRAUD | HIGH | Liveness thấp hoặc phát hiện injection/virtual camera (PAD). |
| `ATM_NO_PERSON` | Giao dịch ATM không có người trước máy | ATM_ATTACK | HIGH | Nghi rút tiền từ xa, relay, malware/jackpotting. |
| `ATM_CAMERA_BLOCKED` | Che/can thiệp camera ATM | ATM_ATTACK | MED | Dấu hiệu chuẩn bị gian lận (skimming, cướp, ép buộc). |
| `ATM_COERCION_OR_SURFING` | Nhiều người trước ATM (ép buộc/nhìn trộm PIN) | CARD_FRAUD | MED | ≥ 2 khuôn mặt trong khung hình. |
| `ATM_CARD_COLLECTION` | Nhiều thẻ của nhiều chủ trên cùng ATM | CARD_FRAUD | MED | ≥ 4 chủ thẻ khác nhau trên một ATM trong 10 phút (thu gom thẻ). |
| `ATM_PIN_AUTOMATED` | Nhập PIN theo nhịp máy | ATM_ATTACK | MED | Hệ số biến thiên khoảng cách phím < 0,05. |
| `AGENT_CASH_OUT` | AI Agent rút tiền mặt | AGENT_ABUSE | MED | ATM là thiết bị vật lý; Agent rút tiền mặt từ xa phải được chủ thẻ xác nhận. |
| `FRAUD_RING` | Vòng gian lận / tài khoản liên kết (đồ thị) | ATO_AML | MED | ≥ 4 khách khác liên kết qua thiết bị/người nhận/IP trong 7 ngày; HIGH khi ≥ 6. Gia đình/doanh nghiệp dùng chung thiết bị cũng tạo liên kết. |
| `STATEMENT_ABUSE` | Lạm dụng thanh toán sao kê (trả thừa rồi rút/hoàn) | CARD_FRAUD | MED | Số tiền trả > 120% dư nợ sao kê. |
| `THIRD_PARTY_PAYMENT` | Người lạ trả nợ thẻ thay (rửa tiền/tài khoản trung gian) | AML | MED | Người thanh toán không phải chủ thẻ, số tiền lớn. |
| `CARD_TO_CARD_CASHOUT` | Thẻ tín dụng trả cho thẻ tín dụng (biến tín dụng thành tiền) | CARD_FRAUD | MED | Nguồn tiền là thẻ tín dụng. |
| `PREPAID_ABUSE` | Nạp thẻ trả trước lớn | AML | MED | Nạp trả trước vượt ngưỡng. |
| `AGENT_VELOCITY_ABUSE` | Agent gửi lệnh dồn dập (velocity) | AGENT_ABUSE | MED | Sát trần số lệnh/giờ. |

## Phân loại cấp cao

* `FRAUD_SUSPECTED` – có ít nhất 1 dấu hiệu HIGH hoặc ≥ 2 dấu hiệu MED.
* `ANOMALY_UNCONFIRMED` – bất thường (trigger KYA hoặc điểm ≥ ngưỡng KYA) nhưng chưa đủ dấu hiệu gian lận → khách xác minh.
* `NORMAL` – không có dấu hiệu.

Mã bất thường có thể hợp lệ (xử lý bằng KYA): `ACTOR_UNVERIFIED`, `AGENT_CASH_OUT`, `AGENT_PROBATION`, `AMOUNT_OVER_KYA`, `ATM_CAMERA_BLOCKED`, `ATM_CAMERA_OFFLINE`, `ATM_CARD_COLLECTION`, `ATM_FACE_UNCERTAIN`, `ATM_FOREIGN`, `ATM_MULTIPLE_FACES`, `ATM_NOT_ENROLLED`, `ATM_PIN_AUTOMATED`, `BALANCE_DRAIN`, `CAPTURE_OVER_PREAUTH`, `CARD_TESTING`, `CC_FUNDS_CC`, `CHIP_FALLBACK`, `CONTACTLESS_NO_CVM`, `DOMESTIC_CARD_ABROAD`, `DORMANT_WAKE`, `FIRST_ONLINE`, `HIGH_RISK_COUNTRY`, `HIGH_RISK_MCC`, `IMPOSSIBLE_TRAVEL`, `LEVERAGE_SPIKE`, `LINKED_ACCOUNTS`, `MANUAL_ENTRY`, `MULE_RECIPIENT`, `NEW_BENEFICIARY`, `NEW_COUNTRY`, `NEW_DEVICE`, `NO_3DS`, `PREPAID_LOAD_HIGH`, `REFUND_OTHER_CARD`, `REFUND_UNMATCHED`, `SESSION_BOT`, `STATEMENT_OVERPAY`, `STATIC_QR_HIGH`, `SUPERVISED_HIGH_RISK`, `THIRD_PARTY_PAYER`.

