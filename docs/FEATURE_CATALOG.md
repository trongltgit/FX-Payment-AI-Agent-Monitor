# Danh mục đặc trưng (Feature Catalog)

Sinh tự động từ `agentmon/catalog.py` – **không sửa tay**. Chạy `python -m tools.gen_docs` để cập nhật.

## Nguồn dữ liệu

| Mã | Nguồn |
|---|---|
| HIST | Lịch sử giao dịch đã thực hiện của chính khách (bảng actions; production: core banking + switch thẻ + log Digibank/Digibiz), tối đa 365 ngày/600 giao dịch gần nhất |
| ATTEMPTS | Các lần Agent gửi lệnh trong 24 giờ gần nhất (mọi trạng thái, kể cả bị chặn) |
| REQUEST | Chính payload giao dịch đang được chấm |
| ACCOUNT | Số dư khả dụng (đã trừ phần đang giữ chỗ KYA/REVIEW) |
| POLICY | Hạn mức hiệu lực MIN(TSC, Chi nhánh, Agent) và danh mục MCC/quốc gia do TSC cấu hình |
| FLAGS | Điểm nghi ngờ (suspicion) tích lũy của khách – cập nhật sau mỗi giao dịch KYA/REVIEW/BLOCK |
| DEVICE | Danh sách thiết bị/ví đã từng thanh toán thành công của khách |

## Cơ sở xây dựng

Các đặc trưng được thiết kế theo **kinh nghiệm nghiệp vụ và các kiểu gian lận đã biết (typology)**, không phải chọn tự động từ nhãn.
Trước khi dùng cho quyết định thật cần kiểm chứng bằng backtest trên dữ liệu có nhãn (xem `docs/DATA_REQUIREMENTS.md`, `python -m agentmon.backtest`).

## Phân hệ FX (24 đặc trưng)

| Đặc trưng | Nhóm | Ý nghĩa | Nguồn | Cơ sở | Typology liên quan |
|---|---|---|---|---|---|
| `amt_log` | BASELINE | log(1+số tiền) | REQUEST | Đưa số tiền về thang log để mô hình không bị chi phối bởi giá trị cực lớn. | — |
| `z` | BASELINE | Độ lệch chuẩn hóa so với trung bình lịch sử cùng loại giao dịch | HIST, REQUEST | Giao dịch lệch mạnh so với thói quen của CHÍNH khách là tín hiệu bất thường cơ bản nhất (chiếm quyền, Agent hoạt động sai). | ACCOUNT_TAKEOVER |
| `ratio` | BASELINE | Số tiền / trung bình lịch sử (cắt tối đa 30) | HIST, REQUEST | Dễ giải thích cho nhân viên duyệt: 'gấp N lần mức thường lệ'. | ACCOUNT_TAKEOVER, FICTITIOUS_PAYMENT |
| `hour_sin` | BASELINE | sin(2π·giờ/24) | REQUEST | Mã hóa giờ giao dịch dạng tuần hoàn (23h gần 0h). | — |
| `hour_cos` | BASELINE | cos(2π·giờ/24) | REQUEST | Cặp với hour_sin. | — |
| `off_hour` | BASELINE | 1 nếu giờ trong 23h–5h (giờ VN) | REQUEST | Giao dịch lớn ngoài giờ là dấu hiệu chiếm quyền/tự động hóa. | OFFHOUR_LARGE, ATM_CASHOUT_ABROAD |
| `atypical_hour` | BASELINE | 1 nếu giờ không nằm trong các giờ thường giao dịch của khách | HIST, REQUEST | Mỗi khách có khung giờ riêng; lệch khung giờ riêng có ý nghĩa hơn lệch khung giờ chung. | ACCOUNT_TAKEOVER |
| `n5` | VELOCITY | Số lệnh của Agent trong 5 phút (gồm lệnh hiện tại) | ATTEMPTS | Dồn lệnh nhanh = bot/Agent lỗi/dò thẻ. | CARD_TESTING, FX_BOT_BURST |
| `n1h` | VELOCITY | Số lệnh trong 1 giờ | ATTEMPTS | So với trần số lệnh/giờ của hạn mức. | FX_BOT_BURST, AGENT_VELOCITY_ABUSE |
| `n24` | VELOCITY | Số lệnh trong 24 giờ | ATTEMPTS | Khối lượng hoạt động theo ngày. | AGENT_VELOCITY_ABUSE |
| `cv_reg` | VELOCITY | 1 − hệ số biến thiên khoảng cách giữa các lệnh (chỉ khi ≥ 8 lệnh/giờ) | ATTEMPTS | Nhịp gửi lệnh đều như máy (metronome) khác hành vi con người; cùng nguyên lý với chấm điểm Anti-Bot. | FX_BOT_BURST |
| `pct_limit` | LIMIT | Số tiền / hạn mức một lần của loại giao dịch (cắt tối đa 3) | REQUEST, POLICY | Sát trần hạn mức là dấu hiệu né hạn mức/dò hạn mức. | STRUCTURING |
| `bal_pct` | LIMIT | Số tiền (FX: ký quỹ) / số dư khả dụng | REQUEST, ACCOUNT | Rút gần hết số dư là hành vi điển hình của chiếm quyền tài khoản/tài khoản trung gian. | FUND_DRAIN_MULE, ACCOUNT_TAKEOVER |
| `dormant` | BASELINE | Số ngày kể từ giao dịch gần nhất / 365 | HIST | Tài khoản ngủ đông bất ngờ hoạt động là dấu hiệu chiếm quyền. | ACCOUNT_TAKEOVER |
| `first_online` | BASELINE | 1 nếu khách chưa từng giao dịch qua kênh online/Agent | HIST | Khách chỉ giao dịch tại quầy bỗng giao dịch online cần xác nhận của chính chủ (KYA). | ACCOUNT_TAKEOVER |
| `thin` | BASELINE | 1 nếu lịch sử cùng loại < 5 giao dịch | HIST | Baseline mỏng thì kết luận 'bất thường' kém chắc chắn – cần biết để mô hình/nhân viên cân nhắc. | — |
| `lev` | TYPOLOGY | Đòn bẩy | REQUEST | Đòn bẩy cao khuếch đại thiệt hại khi Agent sai. | FX_LEVERAGE_ABUSE |
| `lev_ratio` | TYPOLOGY | Đòn bẩy / đòn bẩy trung bình của khách (cắt 20) | HIST, REQUEST | Đòn bẩy tăng đột biến so với thói quen. | FX_LEVERAGE_ABUSE |
| `pair_new` | CONTEXT | 1 nếu cặp tiền chưa từng giao dịch (khi đã có ≥ 5 giao dịch) | HIST, REQUEST | Khách giao dịch ổn định ít khi đổi sang cặp lạ. | ACCOUNT_TAKEOVER |
| `daily_pct` | LIMIT | (Đã dùng trong ngày + lệnh này) / hạn mức ngày (cắt 3) | HIST, REQUEST, POLICY | Cạn hạn mức ngày bằng nhiều lệnh nhỏ. | STRUCTURING |
| `susp` | CONTEXT | Điểm nghi ngờ tích lũy của khách (0–1) | FLAGS | Khách vừa có nhiều giao dịch bị KYA/REVIEW/BLOCK thì giao dịch kế tiếp rủi ro hơn. | — |
| `actor_agent` | CONTEXT | 1 nếu giao dịch do AI Agent gửi, 0 nếu của người dùng | REQUEST | Người và Agent có hành vi khác nhau; mô hình cần biết ai là người thực hiện. | AGENT_VELOCITY_ABUSE |
| `session_risk` | VELOCITY | Điểm bot của phiên người dùng từ Anti-Bot (0–1); Agent = 0 | REQUEST | Phiên người dùng bị Anti-Bot chấm cao (headless, replay, nhịp máy) rồi mới giao dịch là dấu hiệu chiếm quyền/tự động hóa. | SESSION_BOT, ACCOUNT_TAKEOVER |
| `cross_actor_n10` | VELOCITY | Số giao dịch của loại người thực hiện NGƯỢC LẠI (người↔Agent) trên cùng tài khoản trong 10 phút | HIST, ATTEMPTS | Người và Agent cùng thao tác dồn dập trên một tài khoản là dấu hiệu một bên bị điều khiển/chiếm quyền. | ACTOR_CONFLICT |

## Phân hệ PAY (41 đặc trưng)

| Đặc trưng | Nhóm | Ý nghĩa | Nguồn | Cơ sở | Typology liên quan |
|---|---|---|---|---|---|
| `amt_log` | BASELINE | log(1+số tiền) | REQUEST | Đưa số tiền về thang log để mô hình không bị chi phối bởi giá trị cực lớn. | — |
| `z` | BASELINE | Độ lệch chuẩn hóa so với trung bình lịch sử cùng loại giao dịch | HIST, REQUEST | Giao dịch lệch mạnh so với thói quen của CHÍNH khách là tín hiệu bất thường cơ bản nhất (chiếm quyền, Agent hoạt động sai). | ACCOUNT_TAKEOVER |
| `ratio` | BASELINE | Số tiền / trung bình lịch sử (cắt tối đa 30) | HIST, REQUEST | Dễ giải thích cho nhân viên duyệt: 'gấp N lần mức thường lệ'. | ACCOUNT_TAKEOVER, FICTITIOUS_PAYMENT |
| `hour_sin` | BASELINE | sin(2π·giờ/24) | REQUEST | Mã hóa giờ giao dịch dạng tuần hoàn (23h gần 0h). | — |
| `hour_cos` | BASELINE | cos(2π·giờ/24) | REQUEST | Cặp với hour_sin. | — |
| `off_hour` | BASELINE | 1 nếu giờ trong 23h–5h (giờ VN) | REQUEST | Giao dịch lớn ngoài giờ là dấu hiệu chiếm quyền/tự động hóa. | OFFHOUR_LARGE, ATM_CASHOUT_ABROAD |
| `atypical_hour` | BASELINE | 1 nếu giờ không nằm trong các giờ thường giao dịch của khách | HIST, REQUEST | Mỗi khách có khung giờ riêng; lệch khung giờ riêng có ý nghĩa hơn lệch khung giờ chung. | ACCOUNT_TAKEOVER |
| `n5` | VELOCITY | Số lệnh của Agent trong 5 phút (gồm lệnh hiện tại) | ATTEMPTS | Dồn lệnh nhanh = bot/Agent lỗi/dò thẻ. | CARD_TESTING, FX_BOT_BURST |
| `n1h` | VELOCITY | Số lệnh trong 1 giờ | ATTEMPTS | So với trần số lệnh/giờ của hạn mức. | FX_BOT_BURST, AGENT_VELOCITY_ABUSE |
| `n24` | VELOCITY | Số lệnh trong 24 giờ | ATTEMPTS | Khối lượng hoạt động theo ngày. | AGENT_VELOCITY_ABUSE |
| `cv_reg` | VELOCITY | 1 − hệ số biến thiên khoảng cách giữa các lệnh (chỉ khi ≥ 8 lệnh/giờ) | ATTEMPTS | Nhịp gửi lệnh đều như máy (metronome) khác hành vi con người; cùng nguyên lý với chấm điểm Anti-Bot. | FX_BOT_BURST |
| `pct_limit` | LIMIT | Số tiền / hạn mức một lần của loại giao dịch (cắt tối đa 3) | REQUEST, POLICY | Sát trần hạn mức là dấu hiệu né hạn mức/dò hạn mức. | STRUCTURING |
| `bal_pct` | LIMIT | Số tiền (FX: ký quỹ) / số dư khả dụng | REQUEST, ACCOUNT | Rút gần hết số dư là hành vi điển hình của chiếm quyền tài khoản/tài khoản trung gian. | FUND_DRAIN_MULE, ACCOUNT_TAKEOVER |
| `dormant` | BASELINE | Số ngày kể từ giao dịch gần nhất / 365 | HIST | Tài khoản ngủ đông bất ngờ hoạt động là dấu hiệu chiếm quyền. | ACCOUNT_TAKEOVER |
| `first_online` | BASELINE | 1 nếu khách chưa từng giao dịch qua kênh online/Agent | HIST | Khách chỉ giao dịch tại quầy bỗng giao dịch online cần xác nhận của chính chủ (KYA). | ACCOUNT_TAKEOVER |
| `thin` | BASELINE | 1 nếu lịch sử cùng loại < 5 giao dịch | HIST | Baseline mỏng thì kết luận 'bất thường' kém chắc chắn – cần biết để mô hình/nhân viên cân nhắc. | — |
| `is_transfer` | CONTEXT | 1 nếu chuyển tiền | REQUEST | Phân tách hành vi theo loại giao dịch. | — |
| `is_online` | CONTEXT | 1 nếu mua sắm online (E-commerce, CNP) | REQUEST | Phân tách hành vi theo loại giao dịch. | — |
| `is_card` | CONTEXT | 1 nếu thanh toán thẻ tại POS | REQUEST | Phân tách hành vi theo loại giao dịch. | — |
| `new_benef` | CONTEXT | 1 nếu người nhận chưa từng nhận và không thuộc danh sách tin cậy | HIST, REQUEST | Chuyển cho người lạ là bước chính của lừa đảo/chiếm quyền. | ACCOUNT_TAKEOVER, FUND_DRAIN_MULE |
| `benef_cnt` | CONTEXT | log(1+số lần đã chuyển cho người nhận) | HIST | Người nhận quen thuộc rủi ro thấp. | — |
| `new_merchant` | CONTEXT | 1 nếu merchant/biller chưa từng giao dịch (không áp dụng ATM) | HIST, REQUEST | Merchant lạ + giá trị bất thường là mẫu của thanh toán khống/ĐVCNT nghi vấn. | FICTITIOUS_PAYMENT |
| `new_country` | CONTEXT | 1 nếu quốc gia giao dịch chưa từng xuất hiện | HIST, REQUEST | Giao dịch thẻ ở nước mới (nhất là khi thẻ vừa bị lộ). | ACCOUNT_TAKEOVER |
| `hr_country` | TYPOLOGY | 1 nếu quốc gia thuộc danh sách rủi ro cao do TSC cấu hình | REQUEST, POLICY | Chính sách rủi ro quốc gia. | HIGH_RISK_GEO |
| `hr_mcc` | TYPOLOGY | 1 nếu MCC thuộc nhóm rủi ro cao do TSC cấu hình | REQUEST, POLICY | Ngành hàng có tỷ lệ gian lận/chargeback cao. | HIGH_RISK_MCC, FICTITIOUS_PAYMENT |
| `no3ds` | TYPOLOGY | 1 nếu giao dịch CNP vượt ngưỡng mà không có 3-D Secure | REQUEST, POLICY | Không xác thực chủ thẻ trên kênh CNP làm tăng rủi ro gian lận thẻ. | CNP_NO_AUTH |
| `small_burst` | TYPOLOGY | Số giao dịch < 50.000đ trong 10 phút | ATTEMPTS, REQUEST | Chuỗi giao dịch giá trị rất nhỏ là dấu hiệu dò thẻ (card testing). | CARD_TESTING |
| `structuring` | TYPOLOGY | 1 nếu số tiền ở 90%–100% hạn mức/lần | REQUEST, POLICY | Cố ý ở sát trần để né kiểm soát (structuring). | STRUCTURING |
| `round` | TYPOLOGY | 1 nếu số tiền ≥ 1 triệu và tròn triệu | REQUEST | Số tiền tròn lớn xuất hiện nhiều ở giao dịch khống/chuyển tiền lừa đảo. | FICTITIOUS_PAYMENT |
| `decl24` | VELOCITY | Số lần bị chặn trong 24 giờ | ATTEMPTS | Nhiều lần bị từ chối liên tiếp là dấu hiệu dò hạn mức/dò thẻ. | CARD_TESTING |
| `susp` | CONTEXT | Điểm nghi ngờ tích lũy của khách (0–1) | FLAGS | Khách vừa có nhiều giao dịch bị KYA/REVIEW/BLOCK thì giao dịch kế tiếp rủi ro hơn. | — |
| `is_atm` | CONTEXT | 1 nếu rút tiền ATM | REQUEST | ATM là kênh rút tiền mặt – rủi ro cash-out; cần baseline riêng. | ATM_CASHOUT_ABROAD |
| `is_wallet` | CONTEXT | 1 nếu thanh toán qua ví điện tử (Apple Pay/Google Pay…) | REQUEST | Ví gắn với thiết bị; rủi ro nằm ở việc đăng ký thẻ lên thiết bị lạ. | WALLET_DEVICE_ABUSE |
| `is_billqr` | CONTEXT | 1 nếu thanh toán hóa đơn/QR trên Digibank/Digibiz | REQUEST | Kênh số của ngân hàng – baseline merchant/biller riêng. | — |
| `new_device` | TYPOLOGY | 1 nếu giao dịch từ thiết bị chưa từng dùng (ví: kể cả lần đầu; người dùng kênh số: khi đã có lịch sử thiết bị) | DEVICE, REQUEST | Thẻ bị đăng ký lên thiết bị của kẻ gian là kịch bản phổ biến của gian lận ví. | WALLET_DEVICE_ABUSE, ACCOUNT_TAKEOVER |
| `new_channel` | CONTEXT | 1 nếu kênh (POS/CNP/ATM/WALLET/DIGIBANK/DIGIBIZ) chưa từng sử dụng | HIST, REQUEST | Khách đổi kênh đột ngột. | ACCOUNT_TAKEOVER |
| `atm_foreign` | TYPOLOGY | 1 nếu rút tiền ATM ngoài Việt Nam | REQUEST | Cash-out nước ngoài bằng thẻ bị lộ là mẫu gian lận thẻ cổ điển. | ATM_CASHOUT_ABROAD |
| `actor_agent` | CONTEXT | 1 nếu giao dịch do AI Agent gửi, 0 nếu của người dùng | REQUEST | Người và Agent có hành vi khác nhau; mô hình cần biết ai là người thực hiện. | AGENT_VELOCITY_ABUSE |
| `session_risk` | VELOCITY | Điểm bot của phiên người dùng từ Anti-Bot (0–1); Agent = 0 | REQUEST | Phiên người dùng bị Anti-Bot chấm cao (headless, replay, nhịp máy) rồi mới giao dịch là dấu hiệu chiếm quyền/tự động hóa. | SESSION_BOT, ACCOUNT_TAKEOVER |
| `cross_actor_n10` | VELOCITY | Số giao dịch của loại người thực hiện NGƯỢC LẠI (người↔Agent) trên cùng tài khoản trong 10 phút | HIST, ATTEMPTS | Người và Agent cùng thao tác dồn dập trên một tài khoản là dấu hiệu một bên bị điều khiển/chiếm quyền. | ACTOR_CONFLICT |
| `benef_senders` | TYPOLOGY | Số khách KHÁC đã chuyển tới cùng người nhận trong 24 giờ (cắt 10) | HIST | Nhiều khách cùng chuyển vào một tài khoản trong thời gian ngắn là dấu hiệu tài khoản trung gian/thu gom (mule) hoặc lừa đảo hàng loạt. | MULE_COLLECTION |

