# Ma trận tấn công cấp giao dịch (Anti-Bot → Monitor)

| Kịch bản | Kỳ vọng | Thực tế | Phân loại | Luật | KQ |
|---|---|---|---|---|---|
| Người thật: thiết bị chứng thực + MFA + telemetry | MONITOR/* | MONITOR/ALLOW | HUMAN_VERIFIED | - | ĐẠT |
| Script curl, header lạ, xác nhận 50ms | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | BOT_EVIDENCE_STRONG | ĐẠT |
| Nghi bot không khai báo (chỉ xác nhận quá nhanh) | ANTIBOT/CHALLENGE | ANTIBOT/CHALLENGE | SUSPECT | BOT_EVIDENCE_UNCOMPENSATED | ĐẠT |
| Vượt thử thách sau nghi ngờ → qua tầng 1, Monitor xác thực bổ sung | MONITOR/STEP_UP|REVIEW|BLOCK | MONITOR/STEP_UP | HUMAN_LIKELY | CHALLENGE_PASSED_AFTER_SUSPECT | ĐẠT |
| Replay nonce | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | REPLAY | ĐẠT |
| Yêu cầu cũ 1 giờ (dấu thời gian) | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | STALE_REQUEST | ĐẠT |
| Dò BIN: 5 thẻ khác nhau từ một thiết bị | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | CARD_ENUMERATION | ĐẠT |
| Card testing: 6 giao dịch 9.000đ liên tiếp | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | CARD_TESTING | ĐẠT |
| Trang trại tài khoản: 4 khách dùng chung thiết bị | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | DEVICE_FARM | ĐẠT |
| IP đang bị cấm | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | IP_BANNED | ĐẠT |
| AI Agent hợp lệ (nhịp đều là bình thường) | MONITOR/* | MONITOR/ALLOW | AUTOMATION_AUTHORIZED | - | ĐẠT |
| Khóa Agent bị NGƯỜI dùng (chuột/bàn phím) | ANTIBOT/CHALLENGE | ANTIBOT/CHALLENGE | SUSPECT | AGENT_KEY_USED_BY_HUMAN | ĐẠT |
| Agent chạy qua kênh người (AGENT_ECHO) | MONITOR/STEP_UP|REVIEW | MONITOR/REVIEW | HUMAN_VERIFIED | - | ĐẠT |
| ATM: chính chủ (liveness + khuôn mặt khớp) | MONITOR/ALLOW | MONITOR/ALLOW | HUMAN_VERIFIED | - | ĐẠT |
| ATM: virtual camera / deepfake (injection 0,95) | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | PRESENTATION_ATTACK | ĐẠT |
| ATM: không có người trước máy | ANTIBOT/BLOCK | ANTIBOT/BLOCK | MALICIOUS_BOT | NO_PERSON_AT_ATM | ĐẠT |
| ATM: khuôn mặt người khác dùng thẻ | MONITOR/BLOCK | MONITOR/BLOCK | HUMAN_VERIFIED | - | ĐẠT |
| ATM: khuôn mặt chưa chắc → xác nhận qua điện thoại | MONITOR/STEP_UP | MONITOR/STEP_UP | HUMAN_VERIFIED | - | ĐẠT |
| ATM: AI Agent rút tiền mặt từ xa | MONITOR/KYA | MONITOR/KYA | AUTOMATION_AUTHORIZED | - | ĐẠT |
