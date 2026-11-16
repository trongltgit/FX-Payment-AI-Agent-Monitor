"""Danh mục rủi ro cần tránh – nguồn duy nhất cho docs/RISK_REGISTER.md và file Word hướng dẫn.
status: CÓ = đã có kiểm soát trong mã và có test; MỘT PHẦN = có kiểm soát nhưng còn giới hạn; CHƯA = chưa có, cần làm trước khi dùng thật.
Tham chiếu pháp lý chỉ để định hướng: Pháp chế/Tuân thủ phải xác nhận phạm vi áp dụng."""

GROUPS = {
    "A": "Anti-Bot: nhận diện bot và người", "B": "AI Agent", "C": "Xác định người thực hiện (Agent hay người)", "D": "Mô hình AI/ML",
    "E": "Thẻ, QR, thanh toán", "F": "FX", "G": "Dữ liệu, bảo mật, pháp lý", "H": "Hạ tầng và vận hành", "I": "Quản trị và quy trình", "J": "Kiểu gian lận đặc thù", "K": "Sinh trắc, ATM, mô hình AI nâng cao và thẻ",
}

R = [
    # ---- A. Anti-Bot
    ("A1", "A", "Chặn nhầm người thật (false positive) vì nghi là bot", "Gây khó chịu nhưng chỉ ảnh hưởng người thử nghiệm; cần đo tỷ lệ thử thách/chặn người thật.",
     "Mất giao dịch, khiếu nại, rủi ro uy tín. Phải có mục tiêu tỷ lệ chặn nhầm và đường kháng nghị.", "Sổ chứng cứ bot–người; chặn cứng chỉ khi bằng chứng bot mạnh và không có bằng chứng người; mức giữa là THỬ THÁCH, không chặn.", "CÓ", "antibot_txn.py, test_v2"),
    ("A2", "A", "Bỏ lọt bot thật (false negative) vì giả lập hành vi người", "Bot đơn giản bị bắt; bot giả lập tinh vi chưa được đo.",
     "Bot dùng trình duyệt thật, chuột giả, proxy dân cư có thể qua. Cần thử nghiệm đỏ (red team) định kỳ.", "Nhiều lớp độc lập (header, think-time, nhịp, vận tốc thẻ/thiết bị, chứng thực thiết bị); Monitor vẫn chấm điểm rủi ro sau đó.", "MỘT PHẦN", "tools/txn_attack_matrix.py"),
    ("A3", "A", "Kênh nguồn gửi telemetry giả hoặc không gửi", "Demo không bắt buộc telemetry.",
     "Kênh trực tuyến bị coi là đáng ngờ nếu thiếu; nhưng nguồn bị chiếm quyền có thể gửi telemetry giả. Cần chứng thực thiết bị (App Attest/Play Integrity) phía app.", "Pilot/production bắt buộc telemetry cho PORTAL/DIGIBANK/DIGIBIZ; điểm cộng riêng cho thiết bị đã chứng thực.", "MỘT PHẦN", "profiles.py"),
    ("A4", "A", "Replay giao dịch (gửi lại yêu cầu đã chặn bắt được)", "Nonce tùy chọn ở demo.", "Bắt buộc nonce + dấu thời gian; nonce dùng một lần (Redis SETNX).", "Nonce một lần; dấu thời gian lệch > 5 phút bị chặn; production bắt buộc nonce.", "CÓ", "antibot_txn.py"),
    ("A5", "A", "Dò thẻ / card testing / dò BIN", "Có luật theo IP và thiết bị.", "Cần dữ liệu liên-merchant, liên-acquirer; ngưỡng phải hiệu chỉnh theo mùa vụ.", "≥ 6 giao dịch nhỏ/10 phút, ≥ 5 thẻ khác nhau/thiết bị, bão từ chối → chặn tầng 1.", "CÓ", "antibot_txn.py"),
    ("A6", "A", "Trang trại tài khoản / nhiều khách dùng chung một thiết bị", "Luật theo thiết bị.", "Hộ gia đình/doanh nghiệp dùng chung máy hợp lệ: cần danh sách ngoại lệ có phê duyệt.", "≥ 4 khách/24h → chặn; 3 → cộng điểm bot.", "MỘT PHẦN", "antibot_txn.py"),
    ("A7", "A", "Ban nhầm IP dùng chung (CGNAT, chi nhánh, VPN công ty)", "Ít người dùng nên ít ảnh hưởng.", "Ban IP có thể chặn cả khu vực. Chỉ strike IP khách khi nguồn gửi client_ip, không bao giờ IP máy chủ nguồn.", "Strike (không ban ngay) và chỉ trên IP khách; IP máy chủ nguồn không bị đụng.", "CÓ", "pipeline.py"),
    ("A8", "A", "Lỗi hệ thống Anti-Bot (Redis sập) làm cho giao dịch đi qua hoặc kẹt", "Demo cho phép fail-open.", "Fail-closed cho giao dịch tiền; có chế độ suy giảm có kiểm soát và cảnh báo vận hành.", "Pilot/production: lỗi → chặn; demo: cho qua có ghi nhận.", "CÓ", "pipeline.py, test_v2"),
    ("A9", "A", "Né Anti-Bot bằng cách gọi thẳng API Monitor", "Cổng cũ vẫn mở để tương thích.", "Chỉ mở cổng đi qua pipeline; chặn mạng trực tiếp tới engine.", "Mọi cổng (agent-api, txn-api, gateway v2) gọi pipeline.process: tầng 1 luôn chạy trước.", "CÓ", "pipeline.py, test_v2"),
    # ---- B. AI Agent
    ("B1", "B", "Lộ hoặc dùng chung khóa API của Agent", "Khóa nằm trong .env/bộ nhớ demo.", "Khóa lưu KMS/HSM, xoay vòng, gắn dải IP cho phép; thu hồi tức thời.", "Khóa chỉ lưu băm; cấp lại vô hiệu khóa cũ; telemetry tương tác trên khóa Agent → thử thách.", "MỘT PHẦN", "registry.py, antibot_txn.py"),
    ("B2", "B", "Agent bị prompt-injection hoặc bị kẻ gian điều khiển để chuyển tiền", "Rủi ro nằm ở phía Agent của khách.", "Hạn mức theo Agent, phê duyệt của chủ tài khoản (KYA) cho giao dịch bất thường, kill-switch.", "Hạn mức MIN(TSC, chi nhánh, Agent); KYA/xác minh; kill-switch; thử việc cho Agent mới.", "CÓ", "engine.py, kya.py"),
    ("B3", "B", "Agent vòng lặp lỗi gửi lệnh dồn dập", "Có trần số lệnh/giờ, /ngày.", "Cần cầu dao tự động theo khách và theo Agent.", "Trần số lệnh; velocity; tự tạm ngưng khi khách từ chối KYA nhiều lần.", "CÓ", "engine.py"),
    ("B4", "B", "Agent vượt quyền (làm nghiệp vụ không được đăng ký)", "Hard policy chặn.", "Quy trình duyệt đăng ký và rà soát định kỳ.", "Agent phải đăng ký, được chi nhánh duyệt, giới hạn nghiệp vụ/loại giao dịch.", "CÓ", "registry.py"),
    ("B5", "B", "Agent đi vào kênh của người để né kiểm soát Agent (AGENT_ECHO)", "Có kiểm tra khớp giao dịch trong 10 giây.", "Cần thêm dấu vân tay hành vi theo thời gian dài.", "Giao dịch 'của người' trùng khít giao dịch Agent vừa gửi → ACTOR_UNVERIFIED → xác thực bổ sung.", "MỘT PHẦN", "actor.py"),
    ("B6", "B", "TOCTOU: kiểm tra số dư rồi ghi bị xen ngang (FX và thanh toán đồng thời)", "Khóa trong tiến trình và liên tiến trình (cùng máy).", "Nhiều máy cần khóa tư vấn của PostgreSQL theo khách.", "RLock + flock; giữ chỗ số dư; kiểm tra lại khi hạch toán; test hai tiến trình.", "MỘT PHẦN", "engine.py, test_multiprocess"),
    # ---- C. Actor
    ("C1", "C", "Phân loại sai Agent là người hoặc ngược lại", "Phân loại theo luật, tin cậy hiển thị.", "Cần đo độ chính xác phân loại trên dữ liệu thật.", "Độ tin cậy 0–1; dưới 0,65 → không xác minh → ACTOR_UNVERIFIED.", "MỘT PHẦN", "actor.py"),
    ("C2", "C", "Người và Agent cùng thao tác trên một tài khoản", "Có tín hiệu cross_actor_n10.", "Hạn mức cộng gộp người + Agent theo ngày chưa có.", "Tín hiệu chéo; số dư chung; baseline riêng theo người thực hiện khi đủ dữ liệu.", "MỘT PHẦN", "features.py"),
    ("C3", "C", "Nguồn gửi 'khai báo người' nhưng thực chất là Agent chạy hộ", "Khai báo dựa vào khóa nguồn.", "Hợp đồng/SLA với kênh nguồn; kiểm toán định kỳ.", "Anti-Bot quan sát hành vi thay vì tin khai báo; ACTOR_SPOOFING.", "MỘT PHẦN", "antibot_txn.py"),
    # ---- D. Model
    ("D1", "D", "Mô hình huấn luyện trên dữ liệu tổng hợp, không phản ánh thực tế", "Chấp nhận được cho trình diễn; số liệu chỉ là kiểm tra hồi quy.", "BLOCKER: phải huấn luyện/kiểm chứng trên dữ liệu thật có nhãn.", "Công cụ backtest dữ liệu thật; readiness báo BLOCKER nếu mô hình còn dữ liệu tổng hợp.", "CHƯA", "backtest.py, profiles.py"),
    ("D2", "D", "Rò rỉ dữ liệu (data leakage) khi đánh giá", "Tập test khác seed và khách.", "Tách theo thời gian, nhãn đã chín.", "Backtest tách theo thời gian; train chỉ trên giao dịch không gian lận.", "CÓ", "backtest.py"),
    ("D3", "D", "Trôi dữ liệu (drift) làm mô hình lỗi thời", "Không có giám sát drift.", "Giám sát phân phối đặc trưng, tỷ lệ cảnh báo; huấn luyện lại định kỳ.", "Phiên bản hóa mô hình và manifest; chưa có giám sát drift tự động.", "CHƯA", "ml.py"),
    ("D4", "D", "Tỷ lệ báo nhầm cao làm khách bực mình (KYA/STEP_UP quá nhiều)", "Đo trên dữ liệu tổng hợp: ~25% cảnh báo.", "Mục tiêu tỷ lệ xác minh do kinh doanh đặt; hiệu chỉnh ngưỡng từng phân khúc.", "Trigger số tiền lớn chỉ áp khi lệch thói quen; báo cáo nguyên nhân báo nhầm theo trigger.", "MỘT PHẦN", "features.py, backtest.py"),
    ("D5", "D", "Kẻ gian né mô hình (adversarial) bằng giao dịch dưới ngưỡng", "Có luật structuring.", "Thử nghiệm đỏ, luật bổ sung, cập nhật nhanh.", "Luật tách nhỏ/sát hạn mức, velocity, người nhận trung gian.", "MỘT PHẦN", "fraud_types.py"),
    ("D6", "D", "Không giải thích được quyết định khi khiếu nại/kiểm toán", "Có trace.", "Lưu trace tối thiểu theo thời hạn lưu trữ quy định.", "Trace đầy đủ + SHA-256; bản mô hình lưu theo version.", "CÓ", "engine.py"),
    ("D7", "D", "Cold start: khách mới/ít lịch sử bị xử lý quá chặt hoặc quá lỏng", "Baseline mỏng được đánh dấu.", "Chính sách riêng cho khách mới, dữ liệu từ core.", "Cờ 'thin'; điểm riêng; xác minh lần đầu online.", "MỘT PHẦN", "features.py"),
    # ---- E. Card
    ("E1", "E", "Lộ PAN/CVV (PCI-DSS)", "Không dùng thẻ thật ở demo.", "Phạm vi PCI; không lưu PAN/CVV; token hóa; ghi nhật ký không chứa PAN.", "Phát hiện và che PAN/CVV trong payload, chặn và ghi PCI_EXPOSURE; chỉ lưu token và 4 số cuối.", "CÓ", "engine.py"),
    ("E2", "E", "Thẻ giả, skimming, fallback quẹt từ", "Luật chip fallback.", "Cần dữ liệu entry mode từ switch chính xác.", "CHIP_FALLBACK, CONTACTLESS_NO_CVM, DOMESTIC_CARD_ABROAD.", "CÓ", "cardmodel.py"),
    ("E3", "E", "Gian lận CNP/ECOM không xác thực 3DS", "Cờ 3DS.", "Đối chiếu trách nhiệm chuyển dịch (liability shift) theo quy tắc mạng thẻ.", "NO_3DS khi vượt ngưỡng; thẻ ECOM.", "MỘT PHẦN", "features.py"),
    ("E4", "E", "Lạm dụng hoàn tiền, capture vượt pre-auth", "Có luật.", "Cần đối chiếu giao dịch gốc thật.", "REFUND_UNMATCHED, REFUND_OTHER_CARD, CAPTURE_OVER_PREAUTH.", "MỘT PHẦN", "cardmodel.py"),
    ("E5", "E", "Di chuyển bất khả thi (hai quốc gia trong 2 giờ)", "Có luật.", "Cần dữ liệu vị trí/terminal chính xác.", "IMPOSSIBLE_TRAVEL.", "CÓ", "cardmodel.py"),
    ("E6", "E", "Thay mã QR tĩnh / QR giả", "Cờ QR tĩnh lớn.", "Kiểm tra tên merchant hiển thị, danh sách merchant đã xác minh.", "STATIC_QR_HIGH, merchant mới.", "MỘT PHẦN", "cardmodel.py"),
    ("E7", "E", "Merchant khống / thanh toán khống", "Heuristic.", "Cần dữ liệu onboarding ĐVCNT (MID, ngày mở, chargeback).", "FICTITIOUS_PAYMENT theo dấu hiệu.", "MỘT PHẦN", "fraud_types.py"),
    ("E8", "E", "Không phủ hết loại thẻ/giao dịch ở Việt Nam và quốc tế", "Có danh mục Visa, Mastercard, JCB, UnionPay, Amex, Discover/Diners, NAPAS.", "Đối chiếu với danh mục của tổ chức thẻ và NAPAS; thêm trường theo từng quy tắc mạng.", "Danh mục card_network, product, subtype, entry mode, auth, QR.", "MỘT PHẦN", "cardmodel.py"),
    ("E9", "E", "Cờ bạc, quasi-cash, tiền mã hóa, MCC rủi ro", "Danh mục MCC cấu hình.", "TSC duyệt danh mục, cập nhật theo chính sách.", "Chặn cứng MCC cờ bạc; MCC rủi ro → KYA.", "CÓ", "policy.py"),
    # ---- F. FX
    ("F1", "F", "Đòn bẩy lạm dụng, lệnh dồn dập, tự động hóa giá", "Có.", "Giới hạn theo phân khúc/Agent; giám sát độ trượt giá.", "Hạn mức lệnh/ngày, đòn bẩy, velocity; Anti-Bot cấp giao dịch cho FX.", "CÓ", "engine.py"),
    ("F2", "F", "Cào giá và khai thác độ trễ báo giá", "Anti-Bot web có chấm điểm báo giá.", "Hết hạn báo giá ngắn, chống tái sử dụng.", "Anti-Bot web gốc + tầng 1 giao dịch.", "CÓ", "app/transaction.py"),
    ("F3", "F", "FX rồi chuyển tiền ra ngay (đi qua tài khoản)", "Có tín hiệu cross-domain.", "Luật riêng FX→chuyển đi cần dữ liệu thật.", "CROSS_DOMAIN_BURST.", "MỘT PHẦN", "features.py"),
    # ---- G. Data
    ("G1", "G", "Dữ liệu cá nhân (Nghị định 13/2023/NĐ-CP) và quyền riêng tư", "Dữ liệu mẫu.", "Căn cứ pháp lý xử lý, minh bạch, quyền khiếu nại; đánh giá tác động xử lý dữ liệu.", "Không lưu PAN; khách chỉ thấy lý do công khai; nhật ký truy cập giải trình.", "MỘT PHẦN", "reports.py"),
    ("G2", "G", "An toàn hệ thống thông tin ngân hàng (Thông tư 09/2020/TT-NHNN) và các yêu cầu xác thực giao dịch trực tuyến (Quyết định 2345/QĐ-NHNN)", "Chưa áp dụng.", "Pháp chế/Tuân thủ xác nhận phạm vi; xác thực sinh trắc cho giao dịch trên ngưỡng; kiểm toán độc lập.", "STEP_UP có phương thức OTP hoặc sinh trắc; chưa đối chiếu ngưỡng quy định.", "CHƯA", "txn_api.py"),
    ("G3", "G", "Nhật ký bị sửa hoặc mất", "Nhật ký tệp.", "Ghi một chiều (WORM), băm chuỗi, lưu theo thời hạn quy định.", "Audit log, trace_hash; chưa có WORM.", "MỘT PHẦN", "services/audit_log.py"),
    ("G4", "G", "Lộ bí mật cấu hình (.env, khóa)", "Dùng .env.", "KMS/HSM, xoay vòng, không đưa vào ảnh Docker.", "Readiness kiểm tra độ dài và khác biệt; .dockerignore.", "MỘT PHẦN", "profiles.py"),
    ("G5", "G", "Dữ liệu demo lẫn vào production (tài khoản demo, mock_db)", "Demo dùng mock.", "Cổng readiness chặn khởi động production nếu còn CORE_ADAPTER=mock hoặc DEMO_PASSWORD.", "Readiness BLOCKER.", "CÓ", "profiles.py"),
    # ---- H. Infra
    ("H1", "H", "SQLite không chịu tải/đồng thời", "Chấp nhận demo/pilot một máy.", "BLOCKER: chuyển PostgreSQL/Oracle, khóa tư vấn, sao lưu.", "Readiness báo; cơ chế khóa tệp chỉ cho một máy.", "CHƯA", "DEPLOYMENT.md"),
    ("H2", "H", "Độ trễ thời gian thực (giao dịch người cần phản hồi tính bằng mili giây)", "Đo ~23 ms/giao dịch sau khi nạp mô hình (một máy, dữ liệu mẫu).", "Test tải thực tế; không dùng LLM ở đường chính.", "Người: không gọi LLM; chưa test tải.", "MỘT PHẦN", "txn_api.py"),
    ("H3", "H", "Điểm chết đơn (single point of failure)", "Một tiến trình.", "Nhiều bản sao sau cân bằng tải, Redis và CSDL có dự phòng, DR.", "Docker compose, health check TCP.", "CHƯA", "docker-compose.yml"),
    ("H4", "H", "Giám sát và cảnh báo vận hành", "Chỉ nhật ký.", "Số liệu (latency, tỷ lệ chặn/thử thách, lỗi) và cảnh báo.", "Có API sự kiện Anti-Bot và báo cáo; chưa có metrics/alert.", "CHƯA", "api.py"),
    ("H5", "H", "Phụ thuộc LLM (độ trễ, chi phí, rò dữ liệu)", "LLM chỉ nâng mức; chỉ cho Agent.", "Không gửi dữ liệu nhận dạng; cần hợp đồng và chế độ tắt.", "Tóm tắt ẩn danh theo nhóm giá trị; chạy ở vùng xám; mặc định tắt cho người.", "CÓ", "critic.py"),
    # ---- I. Process
    ("I1", "I", "Thay đổi ngưỡng/mô hình không có phê duyệt", "Cấu hình tùy ý ở demo.", "Quy trình phê duyệt hai người, đánh giá tác động trước khi đưa lên.", "Phiên bản mô hình, nhật ký thay đổi chính sách (nhật ký kiểm toán).", "MỘT PHẦN", "policy.py"),
    ("I2", "I", "Thiếu quy trình kháng nghị/hậu kiểm cho khách bị chặn nhầm", "Không có.", "Quy trình, SLA, kênh liên hệ, thống kê.", "REVIEW chờ nhân viên; chưa có luồng kháng nghị khách.", "CHƯA", "engine.py"),
    ("I3", "I", "Không có vòng phản hồi nhãn (KYA bị từ chối, chargeback) để học lại", "Không.", "Kết nối hệ thống vụ việc gian lận để có nhãn.", "Chuẩn dữ liệu nhãn và công cụ backtest; chưa tự động.", "CHƯA", "DATA_REQUIREMENTS.md"),
    ("I4", "I", "Diễn tập thử nghiệm đỏ và kiểm thử bảo mật độc lập", "Có ma trận tấn công nội bộ.", "Pentest độc lập trước go-live, lặp định kỳ.", "tools/attack_matrix.py, tools/txn_attack_matrix.py.", "MỘT PHẦN", "tools/"),
    # ---- J. Typologies
    ("J1", "J", "Chiếm quyền tài khoản (thiết bị mới + người nhận mới + số tiền lớn)", "Có.", "Xác thực sinh trắc/thiết bị tin cậy theo quy định.", "NEW_DEVICE, NEW_BENEFICIARY, ACCOUNT_TAKEOVER, STEP_UP.", "CÓ", "fraud_types.py"),
    ("J2", "J", "Tài khoản trung gian/thu gom tiền (mule)", "Cần nhiều khách; demo có 8.", "Chia sẻ danh sách tài khoản đáng ngờ giữa các ngân hàng.", "benef_senders ≥ 3/5 → MULE_RECIPIENT, MULE_COLLECTION.", "MỘT PHẦN", "features.py"),
    ("K1", "K", "Dữ liệu sinh trắc khuôn mặt là dữ liệu cá nhân NHẠY CẢM (Nghị định 13/2023/NĐ-CP)", "Embedding giả lập, không có người thật.",
     "Chỉ đăng ký khi có đồng ý; mã hóa bằng KMS/HSM; thời hạn lưu; quyền xóa/rút lại; đánh giá tác động xử lý dữ liệu; hợp đồng với nhà cung cấp Face-AI.", "Đồng ý bắt buộc khi đăng ký; embedding mã hóa Fernet; có hàm xóa; không lưu ảnh.", "MỘT PHẦN", "biometrics.py"),
    ("K2", "K", "Tấn công giả mạo sinh trắc: ảnh, video, mặt nạ, virtual camera, deepfake injection", "Có luật theo liveness/injection nhưng dùng số liệu do Face-AI gửi.",
     "Face-AI phải đạt kiểm thử PAD độc lập (ISO/IEC 30107-3); camera/ATM chống tamper; không tin dữ liệu từ thiết bị bị chiếm.", "Liveness thấp/injection cao → BLOCK ở cả hai tầng; ATM_SPOOF_ATTACK.", "MỘT PHẦN", "atm_identity.py, antibot_txn.py"),
    ("K3", "K", "Sai số nhận diện khuôn mặt (FAR/FRR) và thiên lệch theo nhóm người dùng", "Ngưỡng 0,80/0,50 là giá trị mẫu.",
     "Hiệu chỉnh ngưỡng theo nhà cung cấp, kiểm thử công bằng theo độ tuổi/giới/sắc tộc; có đường lui không dùng sinh trắc.", "Vùng trung gian không chặn mà xác nhận qua điện thoại (KYA); mặt không khớp mới chặn.", "MỘT PHẦN", "biometrics.py"),
    ("K4", "K", "Camera ATM hỏng/bị che làm kẹt khách thật hoặc mở lỗ hổng", "Có luật camera OFFLINE/BLOCKED.", "Quy trình dự phòng (xác nhận app, nhân viên), thống kê sự cố theo ATM.", "CAMERA_BLOCKED/OFFLINE → xác nhận qua điện thoại; số tiền lớn → REVIEW.", "MỘT PHẦN", "atm_identity.py"),
    ("K5", "K", "ATM bị tấn công vật lý/logic (relay, jackpotting, skimming, ép buộc)", "Có tín hiệu NO_PERSON, nhiều khuôn mặt, nhiều thẻ/ATM.", "Phối hợp an ninh ATM, giám sát tình trạng thiết bị, chống tamper phần cứng.", "ATM_NO_PERSON, ATM_COERCION_OR_SURFING, ATM_CARD_COLLECTION, ATM_PIN_AUTOMATED.", "MỘT PHẦN", "atm_identity.py"),
    ("K6", "K", "Mô hình AI học có giám sát (bot–người, gradient boosting) quá khớp dữ liệu tổng hợp", "Chạy active ở demo; số liệu chỉ là hồi quy.", "Chạy bóng (shadow) cho tới khi kiểm chứng trên dữ liệu thật có nhãn; theo dõi drift; quyền ghi đè của con người.", "Chế độ shadow mặc định ở pilot/production; chỉ được NÂNG cảnh báo.", "MỘT PHẦN", "profiles.py"),
    ("K7", "K", "Liên kết sai trong đồ thị (gia đình/doanh nghiệp dùng chung thiết bị) gây báo nhầm vòng gian lận", "Ít khách demo.", "Danh sách ngoại lệ được duyệt; chỉ dùng như tín hiệu, không chặn cứng.", "Chỉ cộng điểm và cảnh báo (LINKED_ACCOUNTS); không BLOCK.", "CÓ", "graphrisk.py"),
    ("K8", "K", "Lạm dụng thanh toán sao kê thẻ tín dụng (trả thừa rồi rút/hoàn; trả hộ; thẻ tín dụng trả thẻ tín dụng)", "Có luật.", "Đối soát dư nợ thật từ hệ thống thẻ; giám sát hoàn tiền/ứng tiền mặt sau trả thừa.", "STATEMENT_OVERPAY, THIRD_PARTY_PAYER, CC_FUNDS_CC.", "MỘT PHẦN", "cardmodel.py"),
    ("K9", "K", "Không phủ hết mọi loại thẻ và kiểu gian lận thẻ ở Việt Nam và quốc tế", "Có danh mục mạng, sản phẩm, loại giao dịch, entry mode, QR, sao kê, ATM.", "Đối chiếu danh mục của NAPAS và tổ chức thẻ; thêm quy tắc theo từng mạng; dữ liệu chargeback/fraud report (TC40/SAFE).", "Danh mục cardmodel và hơn 40 kiểu gian lận.", "MỘT PHẦN", "cardmodel.py"),
    ("J3", "J", "Lừa đảo thao túng tâm lý (APP fraud) – khách tự chuyển tiền", "Chưa phát hiện đặc thù.", "Cảnh báo ngữ cảnh, độ trễ chuyển tiền lần đầu, xác nhận người nhận.", "Chỉ qua NEW_BENEFICIARY và số tiền lệch thói quen.", "CHƯA", "—"),
]

STATUS_ORDER = {"CÓ": 0, "MỘT PHẦN": 1, "CHƯA": 2}


def rows():
    return [dict(id=i, group=GROUPS[g], risk=r, demo=d, prod=p, control=c, status=s, ref=ref) for (i, g, r, d, p, c, s, ref) in R]


def summary():
    out = {}
    for r in R:
        out[r[6]] = out.get(r[6], 0) + 1
    return out


def markdown():
    L = ["# Danh mục rủi ro cần tránh (Risk Register)\n",
         "Sinh tự động từ `agentmon/riskregister.py`. Trạng thái: **CÓ** = đã có kiểm soát trong mã và có test; **MỘT PHẦN** = có nhưng còn giới hạn; **CHƯA** = chưa có.",
         "Tham chiếu pháp lý chỉ để định hướng; Pháp chế/Tuân thủ phải xác nhận phạm vi áp dụng.\n",
         f"Tổng: {len(R)} rủi ro – " + ", ".join(f"{k}: {v}" for k, v in sorted(summary().items(), key=lambda x: STATUS_ORDER[x[0]])) + ".\n"]
    for g, name in GROUPS.items():
        L += [f"## {g}. {name}\n", "| ID | Rủi ro | Demo / Pilot | Production | Kiểm soát hiện có | Trạng thái |", "|---|---|---|---|---|---|"]
        for r in R:
            if r[1] == g:
                L.append(f"| {r[0]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | **{r[6]}** |")
        L.append("")
    return "\n".join(L)
