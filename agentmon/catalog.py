"""Danh mục đặc trưng (feature catalog): ý nghĩa nghiệp vụ, nguồn dữ liệu, cơ sở xây dựng, loại hình gian lận liên quan.

Đây là NGUỒN DUY NHẤT cho câu trả lời "cơ sở xây dựng feature là gì, dữ liệu lấy từ đâu".
tests kiểm tra mọi cột trong features.COLS đều có mô tả ở đây; docs/FEATURE_CATALOG.md được sinh từ file này
(python -m tools.gen_docs).
"""

# Nhóm cơ sở: BASELINE = lệch so với thói quen của chính khách; VELOCITY = tốc độ/nhịp gửi lệnh (anti-bot);
# LIMIT = mức sử dụng hạn mức/số dư; CONTEXT = thuộc tính ngữ cảnh giao dịch (merchant, quốc gia, kênh...);
# TYPOLOGY = đặc trưng gắn với một kiểu gian lận đã biết (typology).
SOURCES = {
    "HIST": "Lịch sử giao dịch đã thực hiện của chính khách (bảng actions; production: core banking + switch thẻ + log Digibank/Digibiz), tối đa 365 ngày/600 giao dịch gần nhất",
    "ATTEMPTS": "Các lần Agent gửi lệnh trong 24 giờ gần nhất (mọi trạng thái, kể cả bị chặn)",
    "REQUEST": "Chính payload giao dịch đang được chấm",
    "ACCOUNT": "Số dư khả dụng (đã trừ phần đang giữ chỗ KYA/REVIEW)",
    "POLICY": "Hạn mức hiệu lực MIN(TSC, Chi nhánh, Agent) và danh mục MCC/quốc gia do TSC cấu hình",
    "FLAGS": "Điểm nghi ngờ (suspicion) tích lũy của khách – cập nhật sau mỗi giao dịch KYA/REVIEW/BLOCK",
    "DEVICE": "Danh sách thiết bị/ví đã từng thanh toán thành công của khách",
}

FEATURES = {
    # ---- chung
    "amt_log": dict(group="BASELINE", domains="FX,PAY", sources=["REQUEST"], desc="log(1+số tiền)",
                    why="Đưa số tiền về thang log để mô hình không bị chi phối bởi giá trị cực lớn.", typology=[]),
    "z": dict(group="BASELINE", domains="FX,PAY", sources=["HIST", "REQUEST"], desc="Độ lệch chuẩn hóa so với trung bình lịch sử cùng loại giao dịch",
              why="Giao dịch lệch mạnh so với thói quen của CHÍNH khách là tín hiệu bất thường cơ bản nhất (chiếm quyền, Agent hoạt động sai).", typology=["ACCOUNT_TAKEOVER"]),
    "ratio": dict(group="BASELINE", domains="FX,PAY", sources=["HIST", "REQUEST"], desc="Số tiền / trung bình lịch sử (cắt tối đa 30)",
                  why="Dễ giải thích cho nhân viên duyệt: 'gấp N lần mức thường lệ'.", typology=["ACCOUNT_TAKEOVER", "FICTITIOUS_PAYMENT"]),
    "hour_sin": dict(group="BASELINE", domains="FX,PAY", sources=["REQUEST"], desc="sin(2π·giờ/24)", why="Mã hóa giờ giao dịch dạng tuần hoàn (23h gần 0h).", typology=[]),
    "hour_cos": dict(group="BASELINE", domains="FX,PAY", sources=["REQUEST"], desc="cos(2π·giờ/24)", why="Cặp với hour_sin.", typology=[]),
    "off_hour": dict(group="BASELINE", domains="FX,PAY", sources=["REQUEST"], desc="1 nếu giờ trong 23h–5h (giờ VN)", why="Giao dịch lớn ngoài giờ là dấu hiệu chiếm quyền/tự động hóa.", typology=["OFFHOUR_LARGE", "ATM_CASHOUT_ABROAD"]),
    "atypical_hour": dict(group="BASELINE", domains="FX,PAY", sources=["HIST", "REQUEST"], desc="1 nếu giờ không nằm trong các giờ thường giao dịch của khách",
                          why="Mỗi khách có khung giờ riêng; lệch khung giờ riêng có ý nghĩa hơn lệch khung giờ chung.", typology=["ACCOUNT_TAKEOVER"]),
    "n5": dict(group="VELOCITY", domains="FX,PAY", sources=["ATTEMPTS"], desc="Số lệnh của Agent trong 5 phút (gồm lệnh hiện tại)", why="Dồn lệnh nhanh = bot/Agent lỗi/dò thẻ.", typology=["CARD_TESTING", "FX_BOT_BURST"]),
    "n1h": dict(group="VELOCITY", domains="FX,PAY", sources=["ATTEMPTS"], desc="Số lệnh trong 1 giờ", why="So với trần số lệnh/giờ của hạn mức.", typology=["FX_BOT_BURST", "AGENT_VELOCITY_ABUSE"]),
    "n24": dict(group="VELOCITY", domains="FX,PAY", sources=["ATTEMPTS"], desc="Số lệnh trong 24 giờ", why="Khối lượng hoạt động theo ngày.", typology=["AGENT_VELOCITY_ABUSE"]),
    "cv_reg": dict(group="VELOCITY", domains="FX,PAY", sources=["ATTEMPTS"], desc="1 − hệ số biến thiên khoảng cách giữa các lệnh (chỉ khi ≥ 8 lệnh/giờ)",
                   why="Nhịp gửi lệnh đều như máy (metronome) khác hành vi con người; cùng nguyên lý với chấm điểm Anti-Bot.", typology=["FX_BOT_BURST"]),
    "pct_limit": dict(group="LIMIT", domains="FX,PAY", sources=["REQUEST", "POLICY"], desc="Số tiền / hạn mức một lần của loại giao dịch (cắt tối đa 3)",
                      why="Sát trần hạn mức là dấu hiệu né hạn mức/dò hạn mức.", typology=["STRUCTURING"]),
    "bal_pct": dict(group="LIMIT", domains="FX,PAY", sources=["REQUEST", "ACCOUNT"], desc="Số tiền (FX: ký quỹ) / số dư khả dụng",
                    why="Rút gần hết số dư là hành vi điển hình của chiếm quyền tài khoản/tài khoản trung gian.", typology=["FUND_DRAIN_MULE", "ACCOUNT_TAKEOVER"]),
    "dormant": dict(group="BASELINE", domains="FX,PAY", sources=["HIST"], desc="Số ngày kể từ giao dịch gần nhất / 365", why="Tài khoản ngủ đông bất ngờ hoạt động là dấu hiệu chiếm quyền.", typology=["ACCOUNT_TAKEOVER"]),
    "first_online": dict(group="BASELINE", domains="FX,PAY", sources=["HIST"], desc="1 nếu khách chưa từng giao dịch qua kênh online/Agent",
                         why="Khách chỉ giao dịch tại quầy bỗng giao dịch online cần xác nhận của chính chủ (KYA).", typology=["ACCOUNT_TAKEOVER"]),
    "thin": dict(group="BASELINE", domains="FX,PAY", sources=["HIST"], desc="1 nếu lịch sử cùng loại < 5 giao dịch", why="Baseline mỏng thì kết luận 'bất thường' kém chắc chắn – cần biết để mô hình/nhân viên cân nhắc.", typology=[]),
    "susp": dict(group="CONTEXT", domains="FX,PAY", sources=["FLAGS"], desc="Điểm nghi ngờ tích lũy của khách (0–1)", why="Khách vừa có nhiều giao dịch bị KYA/REVIEW/BLOCK thì giao dịch kế tiếp rủi ro hơn.", typology=[]),
    "actor_agent": dict(group="CONTEXT", domains="FX,PAY", sources=["REQUEST"], desc="1 nếu giao dịch do AI Agent gửi, 0 nếu của người dùng",
                        why="Người và Agent có hành vi khác nhau; mô hình cần biết ai là người thực hiện.", typology=["AGENT_VELOCITY_ABUSE"]),
    "session_risk": dict(group="VELOCITY", domains="FX,PAY", sources=["REQUEST"], desc="Điểm bot của phiên người dùng từ Anti-Bot (0–1); Agent = 0",
                         why="Phiên người dùng bị Anti-Bot chấm cao (headless, replay, nhịp máy) rồi mới giao dịch là dấu hiệu chiếm quyền/tự động hóa.", typology=["SESSION_BOT", "ACCOUNT_TAKEOVER"]),
    "cross_actor_n10": dict(group="VELOCITY", domains="FX,PAY", sources=["HIST", "ATTEMPTS"], desc="Số giao dịch của loại người thực hiện NGƯỢC LẠI (người↔Agent) trên cùng tài khoản trong 10 phút",
                            why="Người và Agent cùng thao tác dồn dập trên một tài khoản là dấu hiệu một bên bị điều khiển/chiếm quyền.", typology=["ACTOR_CONFLICT"]),
    # ---- FX
    "lev": dict(group="TYPOLOGY", domains="FX", sources=["REQUEST"], desc="Đòn bẩy", why="Đòn bẩy cao khuếch đại thiệt hại khi Agent sai.", typology=["FX_LEVERAGE_ABUSE"]),
    "lev_ratio": dict(group="TYPOLOGY", domains="FX", sources=["HIST", "REQUEST"], desc="Đòn bẩy / đòn bẩy trung bình của khách (cắt 20)", why="Đòn bẩy tăng đột biến so với thói quen.", typology=["FX_LEVERAGE_ABUSE"]),
    "pair_new": dict(group="CONTEXT", domains="FX", sources=["HIST", "REQUEST"], desc="1 nếu cặp tiền chưa từng giao dịch (khi đã có ≥ 5 giao dịch)", why="Khách giao dịch ổn định ít khi đổi sang cặp lạ.", typology=["ACCOUNT_TAKEOVER"]),
    "daily_pct": dict(group="LIMIT", domains="FX", sources=["HIST", "REQUEST", "POLICY"], desc="(Đã dùng trong ngày + lệnh này) / hạn mức ngày (cắt 3)", why="Cạn hạn mức ngày bằng nhiều lệnh nhỏ.", typology=["STRUCTURING"]),
    # ---- PAY
    "is_transfer": dict(group="CONTEXT", domains="PAY", sources=["REQUEST"], desc="1 nếu chuyển tiền", why="Phân tách hành vi theo loại giao dịch.", typology=[]),
    "is_online": dict(group="CONTEXT", domains="PAY", sources=["REQUEST"], desc="1 nếu mua sắm online (E-commerce, CNP)", why="Phân tách hành vi theo loại giao dịch.", typology=[]),
    "is_card": dict(group="CONTEXT", domains="PAY", sources=["REQUEST"], desc="1 nếu thanh toán thẻ tại POS", why="Phân tách hành vi theo loại giao dịch.", typology=[]),
    "is_atm": dict(group="CONTEXT", domains="PAY", sources=["REQUEST"], desc="1 nếu rút tiền ATM", why="ATM là kênh rút tiền mặt – rủi ro cash-out; cần baseline riêng.", typology=["ATM_CASHOUT_ABROAD"]),
    "is_wallet": dict(group="CONTEXT", domains="PAY", sources=["REQUEST"], desc="1 nếu thanh toán qua ví điện tử (Apple Pay/Google Pay…)", why="Ví gắn với thiết bị; rủi ro nằm ở việc đăng ký thẻ lên thiết bị lạ.", typology=["WALLET_DEVICE_ABUSE"]),
    "is_billqr": dict(group="CONTEXT", domains="PAY", sources=["REQUEST"], desc="1 nếu thanh toán hóa đơn/QR trên Digibank/Digibiz", why="Kênh số của ngân hàng – baseline merchant/biller riêng.", typology=[]),
    "new_benef": dict(group="CONTEXT", domains="PAY", sources=["HIST", "REQUEST"], desc="1 nếu người nhận chưa từng nhận và không thuộc danh sách tin cậy", why="Chuyển cho người lạ là bước chính của lừa đảo/chiếm quyền.", typology=["ACCOUNT_TAKEOVER", "FUND_DRAIN_MULE"]),
    "benef_cnt": dict(group="CONTEXT", domains="PAY", sources=["HIST"], desc="log(1+số lần đã chuyển cho người nhận)", why="Người nhận quen thuộc rủi ro thấp.", typology=[]),
    "new_merchant": dict(group="CONTEXT", domains="PAY", sources=["HIST", "REQUEST"], desc="1 nếu merchant/biller chưa từng giao dịch (không áp dụng ATM)", why="Merchant lạ + giá trị bất thường là mẫu của thanh toán khống/ĐVCNT nghi vấn.", typology=["FICTITIOUS_PAYMENT"]),
    "new_country": dict(group="CONTEXT", domains="PAY", sources=["HIST", "REQUEST"], desc="1 nếu quốc gia giao dịch chưa từng xuất hiện", why="Giao dịch thẻ ở nước mới (nhất là khi thẻ vừa bị lộ).", typology=["ACCOUNT_TAKEOVER"]),
    "hr_country": dict(group="TYPOLOGY", domains="PAY", sources=["REQUEST", "POLICY"], desc="1 nếu quốc gia thuộc danh sách rủi ro cao do TSC cấu hình", why="Chính sách rủi ro quốc gia.", typology=["HIGH_RISK_GEO"]),
    "hr_mcc": dict(group="TYPOLOGY", domains="PAY", sources=["REQUEST", "POLICY"], desc="1 nếu MCC thuộc nhóm rủi ro cao do TSC cấu hình", why="Ngành hàng có tỷ lệ gian lận/chargeback cao.", typology=["HIGH_RISK_MCC", "FICTITIOUS_PAYMENT"]),
    "no3ds": dict(group="TYPOLOGY", domains="PAY", sources=["REQUEST", "POLICY"], desc="1 nếu giao dịch CNP vượt ngưỡng mà không có 3-D Secure", why="Không xác thực chủ thẻ trên kênh CNP làm tăng rủi ro gian lận thẻ.", typology=["CNP_NO_AUTH"]),
    "small_burst": dict(group="TYPOLOGY", domains="PAY", sources=["ATTEMPTS", "REQUEST"], desc="Số giao dịch < 50.000đ trong 10 phút", why="Chuỗi giao dịch giá trị rất nhỏ là dấu hiệu dò thẻ (card testing).", typology=["CARD_TESTING"]),
    "structuring": dict(group="TYPOLOGY", domains="PAY", sources=["REQUEST", "POLICY"], desc="1 nếu số tiền ở 90%–100% hạn mức/lần", why="Cố ý ở sát trần để né kiểm soát (structuring).", typology=["STRUCTURING"]),
    "round": dict(group="TYPOLOGY", domains="PAY", sources=["REQUEST"], desc="1 nếu số tiền ≥ 1 triệu và tròn triệu", why="Số tiền tròn lớn xuất hiện nhiều ở giao dịch khống/chuyển tiền lừa đảo.", typology=["FICTITIOUS_PAYMENT"]),
    "decl24": dict(group="VELOCITY", domains="PAY", sources=["ATTEMPTS"], desc="Số lần bị chặn trong 24 giờ", why="Nhiều lần bị từ chối liên tiếp là dấu hiệu dò hạn mức/dò thẻ.", typology=["CARD_TESTING"]),
    "benef_senders": dict(group="TYPOLOGY", domains="PAY", sources=["HIST"], desc="Số khách KHÁC đã chuyển tới cùng người nhận trong 24 giờ (cắt 10)",
                          why="Nhiều khách cùng chuyển vào một tài khoản trong thời gian ngắn là dấu hiệu tài khoản trung gian/thu gom (mule) hoặc lừa đảo hàng loạt.", typology=["MULE_COLLECTION"]),
    "new_device": dict(group="TYPOLOGY", domains="PAY", sources=["DEVICE", "REQUEST"], desc="1 nếu giao dịch từ thiết bị chưa từng dùng (ví: kể cả lần đầu; người dùng kênh số: khi đã có lịch sử thiết bị)", why="Thẻ bị đăng ký lên thiết bị của kẻ gian là kịch bản phổ biến của gian lận ví.", typology=["WALLET_DEVICE_ABUSE", "ACCOUNT_TAKEOVER"]),
    "new_channel": dict(group="CONTEXT", domains="PAY", sources=["HIST", "REQUEST"], desc="1 nếu kênh (POS/CNP/ATM/WALLET/DIGIBANK/DIGIBIZ) chưa từng sử dụng", why="Khách đổi kênh đột ngột.", typology=["ACCOUNT_TAKEOVER"]),
    "atm_foreign": dict(group="TYPOLOGY", domains="PAY", sources=["REQUEST"], desc="1 nếu rút tiền ATM ngoài Việt Nam", why="Cash-out nước ngoài bằng thẻ bị lộ là mẫu gian lận thẻ cổ điển.", typology=["ATM_CASHOUT_ABROAD"]),
}


def markdown() -> str:
    from agentmon import features as F
    lines = ["# Danh mục đặc trưng (Feature Catalog)\n",
             "Sinh tự động từ `agentmon/catalog.py` – **không sửa tay**. Chạy `python -m tools.gen_docs` để cập nhật.\n",
             "## Nguồn dữ liệu\n", "| Mã | Nguồn |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in SOURCES.items()]
    lines += ["", "## Cơ sở xây dựng\n",
              "Các đặc trưng được thiết kế theo **kinh nghiệm nghiệp vụ và các kiểu gian lận đã biết (typology)**, không phải chọn tự động từ nhãn.",
              "Trước khi dùng cho quyết định thật cần kiểm chứng bằng backtest trên dữ liệu có nhãn (xem `docs/DATA_REQUIREMENTS.md`, `python -m agentmon.backtest`).\n"]
    for dom in ("FX", "PAY"):
        lines += [f"## Phân hệ {dom} ({len(F.COLS[dom])} đặc trưng)\n", "| Đặc trưng | Nhóm | Ý nghĩa | Nguồn | Cơ sở | Typology liên quan |", "|---|---|---|---|---|---|"]
        for c in F.COLS[dom]:
            m = FEATURES[c]
            lines.append(f"| `{c}` | {m['group']} | {m['desc']} | {', '.join(m['sources'])} | {m['why']} | {', '.join(m['typology']) or '—'} |")
        lines.append("")
    return "\n".join(lines)
