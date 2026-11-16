"""BỘ TIÊU CHÍ (criteria) phân biệt BOT – AI AGENT – NGƯỜI. Nguồn duy nhất cho docs/CRITERIA.md và file Word hướng dẫn.

Nguyên tắc: không dựa vào MỘT tín hiệu. Mỗi tiêu chí cho biết (1) đo bằng trường dữ liệu nào, (2) bot/AI Agent/người thường trông ra sao,
(3) hệ thống dùng nó thế nào (điểm, luật, mô hình). Tham chiếu chuẩn chỉ để định hướng, không có nghĩa hệ thống đã được chứng nhận theo chuẩn đó:
NIST SP 800-63B (mức đảm bảo xác thực), ISO/IEC 30107-3 (phát hiện tấn công giả mạo sinh trắc – PAD), OWASP Automated Threats (OAT: Carding, Card Cracking, Cashing Out)."""

# (id, nhóm, tiêu chí, trường đo, BOT thật, AI AGENT hợp lệ, NGƯỜI thật, cách dùng trong hệ thống, tầng)
C = [
    ("K01", "Danh tính", "Thông tin xác thực", "credential, X-Source-Key, Bearer agk_", "Không có hoặc sai khóa", "Khóa agk_… hợp lệ, Agent đã đăng ký và được duyệt", "Phiên đăng nhập có MFA qua hệ thống nguồn (khóa skx_…)", "Không có → BLOCK (NO_CREDENTIAL); khai báo AGENT/HUMAN suy ra từ loại khóa", "T1"),
    ("K02", "Danh tính", "Đăng ký và phạm vi quyền", "agents.domains/kinds/limits", "Không có đăng ký", "Đăng ký nghiệp vụ, hạn mức, thử việc; giao dịch ngoài phạm vi bị chặn", "Không cần đăng ký; hạn mức theo phân khúc", "Hard Policy; thử việc 3 giao dịch đầu bắt buộc KYA", "T2"),
    ("K03", "Hành vi tương tác", "Thời gian suy nghĩ (từ hiện màn xác nhận đến bấm)", "session.think_time_ms", "< 300 ms hoặc đồng đều", "Không áp dụng (không có màn hình)", "≥ 1,2 giây, biến thiên lớn", "< 300 ms: bot +3; ≥ 1,2 giây kèm chuột/phím: người +3", "T1"),
    ("K04", "Hành vi tương tác", "Nhịp gửi lệnh (hệ số biến thiên khoảng cách)", "ab:cad (CV)", "CV < 0,08 (metronome)", "Đều là BÌNH THƯỜNG, không bị phạt", "CV lớn, bất quy tắc", "Người khai báo mà CV < 0,08 sau ≥ 8 lệnh/5 phút: bot +3", "T1"),
    ("K05", "Hành vi tương tác", "Telemetry chuột/chạm/phím", "pointer_events, key_events, scroll_events, focus_changes", "Không có hoặc rất ít", "Không có; nếu CÓ tương tác trên khóa Agent → nghi người dùng chung khóa", "Có, theo phiên", "Kênh trực tuyến thiếu telemetry: bot +2 (pilot/production); khóa Agent có tương tác → CHALLENGE", "T1"),
    ("K06", "Hành vi tương tác", "Entropy đường đi chuột và biến thiên nhịp phím", "pointer_path_entropy, key_interval_cv", "Thấp (đường thẳng, nhịp đều)", "Không áp dụng", "Cao, không đều", "Đầu vào của mô hình AI bot–người (K15)", "T1"),
    ("K07", "Thiết bị/mạng", "Hồ sơ header và User-Agent", "header_score, User-Agent", "Headless/curl/selenium/python-requests, header lạ", "UA của thư viện/Agent (không bị phạt)", "Giống trình duyệt/ứng dụng ngân hàng", "UA tự động +4; header_score ≥ 40 +3; < 20 người +1", "T1"),
    ("K08", "Thiết bị/mạng", "Chứng thực thiết bị và thiết bị quen", "device_attested, device_known", "Không có", "Không áp dụng", "Có (App Attest/Play Integrity), thiết bị gắn với tài khoản", "Attested người +3; known người +2; thiết bị mới + người nhận mới → xác thực bổ sung", "T1+T2"),
    ("K09", "Thiết bị/mạng", "Uy tín IP/ASN", "ip_reputation, client_ip", "TOR/proxy/trung tâm dữ liệu", "Máy chủ cố định (có thể là datacenter)", "Dân cư/di động", "TOR/PROXY/DATACENTER: bot +2; Agent từ TOR/PROXY → CHALLENGE", "T1"),
    ("K10", "Toàn vẹn yêu cầu", "Replay, nonce, dấu thời gian", "session.nonce, session.ts", "Gửi lại yêu cầu bắt được", "Mỗi yêu cầu có request_id duy nhất", "Mỗi yêu cầu có nonce duy nhất", "Nonce dùng lại hoặc lệch > 5 phút → BLOCK; production bắt buộc nonce", "T1"),
    ("K11", "Xác thực", "Độ mới của MFA và thử thách", "mfa_age_s, pow_ok, turnstile_ok", "Không qua được thử thách", "Không áp dụng", "MFA ≤ 15 phút, qua Turnstile/PoW", "RECENT_MFA +2; CHALLENGE_PASSED +2; vượt thử thách sau nghi ngờ → qua với tin cậy thấp", "T1"),
    ("K12", "Liên kết", "Nhiều tài khoản dùng chung thiết bị/IP/người nhận", "devcust, graphrisk.ring_size", "≥ 4 khách trên một thiết bị/24h", "Một Agent phục vụ một khách", "Thường 1–2 khách (gia đình)", "Tầng 1: DEVICE_FARM; Tầng 2: đồ thị liên kết (LINKED_ACCOUNTS, FRAUD_RING)", "T1+T2"),
    ("K13", "Tấn công thẻ", "Vận tốc thẻ: dò BIN, dò thẻ, bão từ chối", "ab:cards, ab:small, ab:decl", "≥ 5 thẻ/thiết bị; ≥ 6 giao dịch nhỏ; ≥ 60% bị từ chối", "Không (một Agent một khách)", "Rất hiếm", "CARD_ENUMERATION, CARD_TESTING, DECLINE_STORM → BLOCK (OWASP OAT: Carding, Card Cracking)", "T1"),
    ("K14", "Mô hình AI", "Mô hình bot–người (gradient boosting)", "botmodel.score", "Xác suất cao", "Không áp dụng", "Xác suất thấp", "≥ 0,85: bot +3; ≥ 0,6: +2; ≤ 0,15: người +2 (chế độ bóng ở pilot/production)", "T1"),
    ("K15", "Sinh trắc", "Liveness và chống giả mạo (PAD)", "biometric.liveness_score, injection_attack_score", "Ảnh/video/mặt nạ/virtual camera/deepfake", "Không có khuôn mặt", "Liveness cao, không injection", "Liveness ≥ 0,9: người +4; liveness < 0,5 hoặc injection ≥ 0,6 → BLOCK (ISO/IEC 30107-3)", "T1+T2"),
    ("K16", "Sinh trắc", "Khớp khuôn mặt chủ thẻ đã đăng ký", "face_match_score | face_embedding", "Không khớp", "Không áp dụng", "Khớp ≥ 0,80 với mẫu đã đăng ký", "Khớp: người +2; không khớp < 0,50 → BLOCK (người khác dùng thẻ); trung gian → xác nhận qua điện thoại (KYA)", "T2"),
    ("K17", "ATM", "Hiện diện vật lý trước ATM", "biometric.face_present, camera_status", "Giao dịch ATM không có người (relay/malware/rút từ xa)", "AI Agent không thể đứng trước ATM → rút tiền mặt luôn cần chủ thẻ xác nhận", "Có mặt, 1 khuôn mặt", "NO_PERSON → BLOCK; nhiều khuôn mặt → STEP_UP; camera bị che → STEP_UP/REVIEW", "T1+T2"),
    ("K18", "ATM", "Nhịp nhập PIN và số lần sai", "pin_entry_cv, pin_digits, pin_attempts", "Nhịp đều như máy (CV < 0,05)", "Không áp dụng", "Biến thiên tự nhiên", "ATM_PIN_AUTOMATED → xác thực bổ sung; PIN sai ≥ 2 lần +0,15", "T2"),
    ("K19", "ATM", "Nhiều thẻ của nhiều chủ trên cùng ATM", "actions.merchant (ATM) theo 10 phút", "≥ 4 chủ thẻ khác nhau", "Không", "1 thẻ/lần", "ATM_CARD_COLLECTION (thu gom thẻ/skimming)", "T2"),
    ("K20", "Nhất quán", "Khai báo và quan sát có khớp không", "declared_actor vs observed", "Khai báo người nhưng hành vi tự động", "Khóa Agent mà có tương tác của người", "Khai báo người, hành vi người", "ACTOR_UNVERIFIED/ACTOR_SPOOFING; AGENT_ECHO (giao dịch 'của người' y hệt Agent vừa gửi ≤ 10 giây)", "T2"),
    ("K21", "Nhất quán", "Người và Agent cùng thao tác trên một tài khoản", "cross_actor_n10", "—", "—", "—", "≥ 3 giao dịch của loại ngược lại/10 phút → +0,15 velocity, ACTOR_CONFLICT", "T2"),
    ("K22", "Hành vi giao dịch", "Lệch thói quen của chính khách", "z, ratio, atypical_hour, dormant, first_online…", "Lệch mạnh", "Lệch nếu Agent bị điều khiển", "Theo thói quen", "Isolation Forest + hành vi + gradient boosting thứ hai + chuỗi hành vi (Markov)", "T2"),
    ("K23", "Hành vi giao dịch", "Chuỗi hành vi (loại giao dịch → kênh → ngành hàng)", "seqmodel.surprise", "Chuỗi lạ", "Chuỗi lặp ổn định", "Chuỗi quen thuộc", "Độ bất ngờ ≥ 0,85: +0,10 hành vi", "T2"),
    ("K24", "Phản hồi", "Hành vi sau thử thách", "turnstile_ok, kết quả STEP_UP/KYA", "Không vượt hoặc lặp lại tấn công", "Chủ tài khoản duyệt KYA", "Vượt thử thách, nhập OTP/sinh trắc đúng", "Thất bại tăng điểm nghi ngờ khách (+0,20); KYA bị từ chối nhiều lần tạm ngưng Agent", "T2"),
]


def rows():
    return [dict(id=r[0], group=r[1], criterion=r[2], field=r[3], bot=r[4], agent=r[5], human=r[6], use=r[7], layer=r[8]) for r in C]


def markdown():
    L = ["# Bộ tiêu chí phân biệt BOT – AI AGENT – NGƯỜI\n",
         "Sinh tự động từ `agentmon/criteria.py`. Hệ thống **không dựa vào một tín hiệu**; mỗi tiêu chí đóng góp bằng chứng cho phía bot hoặc phía người, "
         "AI Agent hợp lệ được nhận diện bằng khóa + đăng ký và **không bị phạt vì tự động hóa**.\n",
         "Tham chiếu định hướng (không phải chứng nhận): NIST SP 800-63B, ISO/IEC 30107-3 (PAD), OWASP Automated Threats (OAT).\n",
         "| ID | Nhóm | Tiêu chí | Trường đo | BOT thật | AI Agent hợp lệ | Người thật | Cách dùng | Tầng |", "|---|---|---|---|---|---|---|---|---|"]
    L += [f"| {r[0]} | {r[1]} | {r[2]} | {r[3]} | {r[4]} | {r[5]} | {r[6]} | {r[7]} | {r[8]} |" for r in C]
    return "\n".join(L) + "\n"
