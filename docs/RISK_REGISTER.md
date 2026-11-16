# Danh mục rủi ro cần tránh (Risk Register)

Sinh tự động từ `agentmon/riskregister.py`. Trạng thái: **CÓ** = đã có kiểm soát trong mã và có test; **MỘT PHẦN** = có nhưng còn giới hạn; **CHƯA** = chưa có.
Tham chiếu pháp lý chỉ để định hướng; Pháp chế/Tuân thủ phải xác nhận phạm vi áp dụng.

Tổng: 63 rủi ro – CÓ: 21, MỘT PHẦN: 33, CHƯA: 9.

## A. Anti-Bot: nhận diện bot và người

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| A1 | Chặn nhầm người thật (false positive) vì nghi là bot | Gây khó chịu nhưng chỉ ảnh hưởng người thử nghiệm; cần đo tỷ lệ thử thách/chặn người thật. | Mất giao dịch, khiếu nại, rủi ro uy tín. Phải có mục tiêu tỷ lệ chặn nhầm và đường kháng nghị. | Sổ chứng cứ bot–người; chặn cứng chỉ khi bằng chứng bot mạnh và không có bằng chứng người; mức giữa là THỬ THÁCH, không chặn. | **CÓ** |
| A2 | Bỏ lọt bot thật (false negative) vì giả lập hành vi người | Bot đơn giản bị bắt; bot giả lập tinh vi chưa được đo. | Bot dùng trình duyệt thật, chuột giả, proxy dân cư có thể qua. Cần thử nghiệm đỏ (red team) định kỳ. | Nhiều lớp độc lập (header, think-time, nhịp, vận tốc thẻ/thiết bị, chứng thực thiết bị); Monitor vẫn chấm điểm rủi ro sau đó. | **MỘT PHẦN** |
| A3 | Kênh nguồn gửi telemetry giả hoặc không gửi | Demo không bắt buộc telemetry. | Kênh trực tuyến bị coi là đáng ngờ nếu thiếu; nhưng nguồn bị chiếm quyền có thể gửi telemetry giả. Cần chứng thực thiết bị (App Attest/Play Integrity) phía app. | Pilot/production bắt buộc telemetry cho PORTAL/DIGIBANK/DIGIBIZ; điểm cộng riêng cho thiết bị đã chứng thực. | **MỘT PHẦN** |
| A4 | Replay giao dịch (gửi lại yêu cầu đã chặn bắt được) | Nonce tùy chọn ở demo. | Bắt buộc nonce + dấu thời gian; nonce dùng một lần (Redis SETNX). | Nonce một lần; dấu thời gian lệch > 5 phút bị chặn; production bắt buộc nonce. | **CÓ** |
| A5 | Dò thẻ / card testing / dò BIN | Có luật theo IP và thiết bị. | Cần dữ liệu liên-merchant, liên-acquirer; ngưỡng phải hiệu chỉnh theo mùa vụ. | ≥ 6 giao dịch nhỏ/10 phút, ≥ 5 thẻ khác nhau/thiết bị, bão từ chối → chặn tầng 1. | **CÓ** |
| A6 | Trang trại tài khoản / nhiều khách dùng chung một thiết bị | Luật theo thiết bị. | Hộ gia đình/doanh nghiệp dùng chung máy hợp lệ: cần danh sách ngoại lệ có phê duyệt. | ≥ 4 khách/24h → chặn; 3 → cộng điểm bot. | **MỘT PHẦN** |
| A7 | Ban nhầm IP dùng chung (CGNAT, chi nhánh, VPN công ty) | Ít người dùng nên ít ảnh hưởng. | Ban IP có thể chặn cả khu vực. Chỉ strike IP khách khi nguồn gửi client_ip, không bao giờ IP máy chủ nguồn. | Strike (không ban ngay) và chỉ trên IP khách; IP máy chủ nguồn không bị đụng. | **CÓ** |
| A8 | Lỗi hệ thống Anti-Bot (Redis sập) làm cho giao dịch đi qua hoặc kẹt | Demo cho phép fail-open. | Fail-closed cho giao dịch tiền; có chế độ suy giảm có kiểm soát và cảnh báo vận hành. | Pilot/production: lỗi → chặn; demo: cho qua có ghi nhận. | **CÓ** |
| A9 | Né Anti-Bot bằng cách gọi thẳng API Monitor | Cổng cũ vẫn mở để tương thích. | Chỉ mở cổng đi qua pipeline; chặn mạng trực tiếp tới engine. | Mọi cổng (agent-api, txn-api, gateway v2) gọi pipeline.process: tầng 1 luôn chạy trước. | **CÓ** |

## B. AI Agent

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| B1 | Lộ hoặc dùng chung khóa API của Agent | Khóa nằm trong .env/bộ nhớ demo. | Khóa lưu KMS/HSM, xoay vòng, gắn dải IP cho phép; thu hồi tức thời. | Khóa chỉ lưu băm; cấp lại vô hiệu khóa cũ; telemetry tương tác trên khóa Agent → thử thách. | **MỘT PHẦN** |
| B2 | Agent bị prompt-injection hoặc bị kẻ gian điều khiển để chuyển tiền | Rủi ro nằm ở phía Agent của khách. | Hạn mức theo Agent, phê duyệt của chủ tài khoản (KYA) cho giao dịch bất thường, kill-switch. | Hạn mức MIN(TSC, chi nhánh, Agent); KYA/xác minh; kill-switch; thử việc cho Agent mới. | **CÓ** |
| B3 | Agent vòng lặp lỗi gửi lệnh dồn dập | Có trần số lệnh/giờ, /ngày. | Cần cầu dao tự động theo khách và theo Agent. | Trần số lệnh; velocity; tự tạm ngưng khi khách từ chối KYA nhiều lần. | **CÓ** |
| B4 | Agent vượt quyền (làm nghiệp vụ không được đăng ký) | Hard policy chặn. | Quy trình duyệt đăng ký và rà soát định kỳ. | Agent phải đăng ký, được chi nhánh duyệt, giới hạn nghiệp vụ/loại giao dịch. | **CÓ** |
| B5 | Agent đi vào kênh của người để né kiểm soát Agent (AGENT_ECHO) | Có kiểm tra khớp giao dịch trong 10 giây. | Cần thêm dấu vân tay hành vi theo thời gian dài. | Giao dịch 'của người' trùng khít giao dịch Agent vừa gửi → ACTOR_UNVERIFIED → xác thực bổ sung. | **MỘT PHẦN** |
| B6 | TOCTOU: kiểm tra số dư rồi ghi bị xen ngang (FX và thanh toán đồng thời) | Khóa trong tiến trình và liên tiến trình (cùng máy). | Nhiều máy cần khóa tư vấn của PostgreSQL theo khách. | RLock + flock; giữ chỗ số dư; kiểm tra lại khi hạch toán; test hai tiến trình. | **MỘT PHẦN** |

## C. Xác định người thực hiện (Agent hay người)

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| C1 | Phân loại sai Agent là người hoặc ngược lại | Phân loại theo luật, tin cậy hiển thị. | Cần đo độ chính xác phân loại trên dữ liệu thật. | Độ tin cậy 0–1; dưới 0,65 → không xác minh → ACTOR_UNVERIFIED. | **MỘT PHẦN** |
| C2 | Người và Agent cùng thao tác trên một tài khoản | Có tín hiệu cross_actor_n10. | Hạn mức cộng gộp người + Agent theo ngày chưa có. | Tín hiệu chéo; số dư chung; baseline riêng theo người thực hiện khi đủ dữ liệu. | **MỘT PHẦN** |
| C3 | Nguồn gửi 'khai báo người' nhưng thực chất là Agent chạy hộ | Khai báo dựa vào khóa nguồn. | Hợp đồng/SLA với kênh nguồn; kiểm toán định kỳ. | Anti-Bot quan sát hành vi thay vì tin khai báo; ACTOR_SPOOFING. | **MỘT PHẦN** |

## D. Mô hình AI/ML

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| D1 | Mô hình huấn luyện trên dữ liệu tổng hợp, không phản ánh thực tế | Chấp nhận được cho trình diễn; số liệu chỉ là kiểm tra hồi quy. | BLOCKER: phải huấn luyện/kiểm chứng trên dữ liệu thật có nhãn. | Công cụ backtest dữ liệu thật; readiness báo BLOCKER nếu mô hình còn dữ liệu tổng hợp. | **CHƯA** |
| D2 | Rò rỉ dữ liệu (data leakage) khi đánh giá | Tập test khác seed và khách. | Tách theo thời gian, nhãn đã chín. | Backtest tách theo thời gian; train chỉ trên giao dịch không gian lận. | **CÓ** |
| D3 | Trôi dữ liệu (drift) làm mô hình lỗi thời | Không có giám sát drift. | Giám sát phân phối đặc trưng, tỷ lệ cảnh báo; huấn luyện lại định kỳ. | Phiên bản hóa mô hình và manifest; chưa có giám sát drift tự động. | **CHƯA** |
| D4 | Tỷ lệ báo nhầm cao làm khách bực mình (KYA/STEP_UP quá nhiều) | Đo trên dữ liệu tổng hợp: ~25% cảnh báo. | Mục tiêu tỷ lệ xác minh do kinh doanh đặt; hiệu chỉnh ngưỡng từng phân khúc. | Trigger số tiền lớn chỉ áp khi lệch thói quen; báo cáo nguyên nhân báo nhầm theo trigger. | **MỘT PHẦN** |
| D5 | Kẻ gian né mô hình (adversarial) bằng giao dịch dưới ngưỡng | Có luật structuring. | Thử nghiệm đỏ, luật bổ sung, cập nhật nhanh. | Luật tách nhỏ/sát hạn mức, velocity, người nhận trung gian. | **MỘT PHẦN** |
| D6 | Không giải thích được quyết định khi khiếu nại/kiểm toán | Có trace. | Lưu trace tối thiểu theo thời hạn lưu trữ quy định. | Trace đầy đủ + SHA-256; bản mô hình lưu theo version. | **CÓ** |
| D7 | Cold start: khách mới/ít lịch sử bị xử lý quá chặt hoặc quá lỏng | Baseline mỏng được đánh dấu. | Chính sách riêng cho khách mới, dữ liệu từ core. | Cờ 'thin'; điểm riêng; xác minh lần đầu online. | **MỘT PHẦN** |

## E. Thẻ, QR, thanh toán

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| E1 | Lộ PAN/CVV (PCI-DSS) | Không dùng thẻ thật ở demo. | Phạm vi PCI; không lưu PAN/CVV; token hóa; ghi nhật ký không chứa PAN. | Phát hiện và che PAN/CVV trong payload, chặn và ghi PCI_EXPOSURE; chỉ lưu token và 4 số cuối. | **CÓ** |
| E2 | Thẻ giả, skimming, fallback quẹt từ | Luật chip fallback. | Cần dữ liệu entry mode từ switch chính xác. | CHIP_FALLBACK, CONTACTLESS_NO_CVM, DOMESTIC_CARD_ABROAD. | **CÓ** |
| E3 | Gian lận CNP/ECOM không xác thực 3DS | Cờ 3DS. | Đối chiếu trách nhiệm chuyển dịch (liability shift) theo quy tắc mạng thẻ. | NO_3DS khi vượt ngưỡng; thẻ ECOM. | **MỘT PHẦN** |
| E4 | Lạm dụng hoàn tiền, capture vượt pre-auth | Có luật. | Cần đối chiếu giao dịch gốc thật. | REFUND_UNMATCHED, REFUND_OTHER_CARD, CAPTURE_OVER_PREAUTH. | **MỘT PHẦN** |
| E5 | Di chuyển bất khả thi (hai quốc gia trong 2 giờ) | Có luật. | Cần dữ liệu vị trí/terminal chính xác. | IMPOSSIBLE_TRAVEL. | **CÓ** |
| E6 | Thay mã QR tĩnh / QR giả | Cờ QR tĩnh lớn. | Kiểm tra tên merchant hiển thị, danh sách merchant đã xác minh. | STATIC_QR_HIGH, merchant mới. | **MỘT PHẦN** |
| E7 | Merchant khống / thanh toán khống | Heuristic. | Cần dữ liệu onboarding ĐVCNT (MID, ngày mở, chargeback). | FICTITIOUS_PAYMENT theo dấu hiệu. | **MỘT PHẦN** |
| E8 | Không phủ hết loại thẻ/giao dịch ở Việt Nam và quốc tế | Có danh mục Visa, Mastercard, JCB, UnionPay, Amex, Discover/Diners, NAPAS. | Đối chiếu với danh mục của tổ chức thẻ và NAPAS; thêm trường theo từng quy tắc mạng. | Danh mục card_network, product, subtype, entry mode, auth, QR. | **MỘT PHẦN** |
| E9 | Cờ bạc, quasi-cash, tiền mã hóa, MCC rủi ro | Danh mục MCC cấu hình. | TSC duyệt danh mục, cập nhật theo chính sách. | Chặn cứng MCC cờ bạc; MCC rủi ro → KYA. | **CÓ** |

## F. FX

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| F1 | Đòn bẩy lạm dụng, lệnh dồn dập, tự động hóa giá | Có. | Giới hạn theo phân khúc/Agent; giám sát độ trượt giá. | Hạn mức lệnh/ngày, đòn bẩy, velocity; Anti-Bot cấp giao dịch cho FX. | **CÓ** |
| F2 | Cào giá và khai thác độ trễ báo giá | Anti-Bot web có chấm điểm báo giá. | Hết hạn báo giá ngắn, chống tái sử dụng. | Anti-Bot web gốc + tầng 1 giao dịch. | **CÓ** |
| F3 | FX rồi chuyển tiền ra ngay (đi qua tài khoản) | Có tín hiệu cross-domain. | Luật riêng FX→chuyển đi cần dữ liệu thật. | CROSS_DOMAIN_BURST. | **MỘT PHẦN** |

## G. Dữ liệu, bảo mật, pháp lý

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| G1 | Dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP) và quyền riêng tư | Dữ liệu mẫu. | Căn cứ pháp lý xử lý, minh bạch, quyền khiếu nại; đánh giá tác động xử lý dữ liệu. | Không lưu PAN; khách chỉ thấy lý do công khai; nhật ký truy cập giải trình. | **MỘT PHẦN** |
| G2 | An toàn hệ thống thông tin ngân hàng (Thông tư 09/2020/TT-NHNN) và các yêu cầu xác thực giao dịch trực tuyến (Quyết định 2345/QĐ-NHNN) | Chưa áp dụng. | Pháp chế/Tuân thủ xác nhận phạm vi; xác thực sinh trắc cho giao dịch trên ngưỡng; kiểm toán độc lập. | STEP_UP có phương thức OTP hoặc sinh trắc; chưa đối chiếu ngưỡng quy định. | **CHƯA** |
| G3 | Nhật ký bị sửa hoặc mất | Nhật ký tệp. | Ghi một chiều (WORM), băm chuỗi, lưu theo thời hạn quy định. | Audit log, trace_hash; chưa có WORM. | **MỘT PHẦN** |
| G4 | Lộ bí mật cấu hình (.env, khóa) | Dùng .env. | KMS/HSM, xoay vòng, không đưa vào ảnh Docker. | Readiness kiểm tra độ dài và khác biệt; .dockerignore. | **MỘT PHẦN** |
| G5 | Dữ liệu demo lẫn vào production (tài khoản demo, mock_db) | Demo dùng mock. | Cổng readiness chặn khởi động production nếu còn CORE_ADAPTER=mock hoặc DEMO_PASSWORD. | Readiness BLOCKER. | **CÓ** |

## H. Hạ tầng và vận hành

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| H1 | SQLite không chịu tải/đồng thời | Chấp nhận demo/pilot một máy. | BLOCKER: chuyển PostgreSQL/Oracle, khóa tư vấn, sao lưu. | Readiness báo; cơ chế khóa tệp chỉ cho một máy. | **CHƯA** |
| H2 | Độ trễ thời gian thực (giao dịch người cần phản hồi tính bằng mili giây) | Đo ~23 ms/giao dịch sau khi nạp mô hình (một máy, dữ liệu mẫu). | Test tải thực tế; không dùng LLM ở đường chính. | Người: không gọi LLM; chưa test tải. | **MỘT PHẦN** |
| H3 | Điểm chết đơn (single point of failure) | Một tiến trình. | Nhiều bản sao sau cân bằng tải, Redis và CSDL có dự phòng, DR. | Docker compose, health check TCP. | **CHƯA** |
| H4 | Giám sát và cảnh báo vận hành | Chỉ nhật ký. | Số liệu (latency, tỷ lệ chặn/thử thách, lỗi) và cảnh báo. | Có API sự kiện Anti-Bot và báo cáo; chưa có metrics/alert. | **CHƯA** |
| H5 | Phụ thuộc LLM (độ trễ, chi phí, rò dữ liệu) | LLM chỉ nâng mức; chỉ cho Agent. | Không gửi dữ liệu nhận dạng; cần hợp đồng và chế độ tắt. | Tóm tắt ẩn danh theo nhóm giá trị; chạy ở vùng xám; mặc định tắt cho người. | **CÓ** |

## I. Quản trị và quy trình

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| I1 | Thay đổi ngưỡng/mô hình không có phê duyệt | Cấu hình tùy ý ở demo. | Quy trình phê duyệt hai người, đánh giá tác động trước khi đưa lên. | Phiên bản mô hình, nhật ký thay đổi chính sách (nhật ký kiểm toán). | **MỘT PHẦN** |
| I2 | Thiếu quy trình kháng nghị/hậu kiểm cho khách bị chặn nhầm | Không có. | Quy trình, SLA, kênh liên hệ, thống kê. | REVIEW chờ nhân viên; chưa có luồng kháng nghị khách. | **CHƯA** |
| I3 | Không có vòng phản hồi nhãn (KYA bị từ chối, chargeback) để học lại | Không. | Kết nối hệ thống vụ việc gian lận để có nhãn. | Chuẩn dữ liệu nhãn và công cụ backtest; chưa tự động. | **CHƯA** |
| I4 | Diễn tập thử nghiệm đỏ và kiểm thử bảo mật độc lập | Có ma trận tấn công nội bộ. | Pentest độc lập trước go-live, lặp định kỳ. | tools/attack_matrix.py, tools/txn_attack_matrix.py. | **MỘT PHẦN** |

## J. Kiểu gian lận đặc thù

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| J1 | Chiếm quyền tài khoản (thiết bị mới + người nhận mới + số tiền lớn) | Có. | Xác thực sinh trắc/thiết bị tin cậy theo quy định. | NEW_DEVICE, NEW_BENEFICIARY, ACCOUNT_TAKEOVER, STEP_UP. | **CÓ** |
| J2 | Tài khoản trung gian/thu gom tiền (mule) | Cần nhiều khách; demo có 8. | Chia sẻ danh sách tài khoản đáng ngờ giữa các ngân hàng. | benef_senders ≥ 3/5 → MULE_RECIPIENT, MULE_COLLECTION. | **MỘT PHẦN** |
| J3 | Lừa đảo thao túng tâm lý (APP fraud) – khách tự chuyển tiền | Chưa phát hiện đặc thù. | Cảnh báo ngữ cảnh, độ trễ chuyển tiền lần đầu, xác nhận người nhận. | Chỉ qua NEW_BENEFICIARY và số tiền lệch thói quen. | **CHƯA** |

## K. Sinh trắc, ATM, mô hình AI nâng cao và thẻ

| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |
|---|---|---|---|---|---|
| K1 | Dữ liệu sinh trắc khuôn mặt là dữ liệu cá nhân NHẠY CẢM (Nghị định 13/2023/NĐ-CP) | Embedding giả lập, không có người thật. | Chỉ đăng ký khi có đồng ý; mã hóa bằng KMS/HSM; thời hạn lưu; quyền xóa/rút lại; đánh giá tác động xử lý dữ liệu; hợp đồng với nhà cung cấp Face-AI. | Đồng ý bắt buộc khi đăng ký; embedding mã hóa Fernet; có hàm xóa; không lưu ảnh. | **MỘT PHẦN** |
| K2 | Tấn công giả mạo sinh trắc: ảnh, video, mặt nạ, virtual camera, deepfake injection | Có luật theo liveness/injection nhưng dùng số liệu do Face-AI gửi. | Face-AI phải đạt kiểm thử PAD độc lập (ISO/IEC 30107-3); camera/ATM chống tamper; không tin dữ liệu từ thiết bị bị chiếm. | Liveness thấp/injection cao → BLOCK ở cả hai tầng; ATM_SPOOF_ATTACK. | **MỘT PHẦN** |
| K3 | Sai số nhận diện khuôn mặt (FAR/FRR) và thiên lệch theo nhóm người dùng | Ngưỡng 0,80/0,50 là giá trị mẫu. | Hiệu chỉnh ngưỡng theo nhà cung cấp, kiểm thử công bằng theo độ tuổi/giới/sắc tộc; có đường lui không dùng sinh trắc. | Vùng trung gian không chặn mà xác nhận qua điện thoại (KYA); mặt không khớp mới chặn. | **MỘT PHẦN** |
| K4 | Camera ATM hỏng/bị che làm kẹt khách thật hoặc mở lỗ hổng | Có luật camera OFFLINE/BLOCKED. | Quy trình dự phòng (xác nhận app, nhân viên), thống kê sự cố theo ATM. | CAMERA_BLOCKED/OFFLINE → xác nhận qua điện thoại; số tiền lớn → REVIEW. | **MỘT PHẦN** |
| K5 | ATM bị tấn công vật lý/logic (relay, jackpotting, skimming, ép buộc) | Có tín hiệu NO_PERSON, nhiều khuôn mặt, nhiều thẻ/ATM. | Phối hợp an ninh ATM, giám sát tình trạng thiết bị, chống tamper phần cứng. | ATM_NO_PERSON, ATM_COERCION_OR_SURFING, ATM_CARD_COLLECTION, ATM_PIN_AUTOMATED. | **MỘT PHẦN** |
| K6 | Mô hình AI học có giám sát (bot–người, gradient boosting) quá khớp dữ liệu tổng hợp | Chạy active ở demo; số liệu chỉ là hồi quy. | Chạy bóng (shadow) cho tới khi kiểm chứng trên dữ liệu thật có nhãn; theo dõi drift; quyền ghi đè của con người. | Chế độ shadow mặc định ở pilot/production; chỉ được NÂNG cảnh báo. | **MỘT PHẦN** |
| K7 | Liên kết sai trong đồ thị (gia đình/doanh nghiệp dùng chung thiết bị) gây báo nhầm vòng gian lận | Ít khách demo. | Danh sách ngoại lệ được duyệt; chỉ dùng như tín hiệu, không chặn cứng. | Chỉ cộng điểm và cảnh báo (LINKED_ACCOUNTS); không BLOCK. | **CÓ** |
| K8 | Lạm dụng thanh toán sao kê thẻ tín dụng (trả thừa rồi rút/hoàn; trả hộ; thẻ tín dụng trả thẻ tín dụng) | Có luật. | Đối soát dư nợ thật từ hệ thống thẻ; giám sát hoàn tiền/ứng tiền mặt sau trả thừa. | STATEMENT_OVERPAY, THIRD_PARTY_PAYER, CC_FUNDS_CC. | **MỘT PHẦN** |
| K9 | Không phủ hết mọi loại thẻ và kiểu gian lận thẻ ở Việt Nam và quốc tế | Có danh mục mạng, sản phẩm, loại giao dịch, entry mode, QR, sao kê, ATM. | Đối chiếu danh mục của NAPAS và tổ chức thẻ; thêm quy tắc theo từng mạng; dữ liệu chargeback/fraud report (TC40/SAFE). | Danh mục cardmodel và hơn 40 kiểu gian lận. | **MỘT PHẦN** |

