"""Sinh PDF hướng dẫn nguyên tắc & vận hành. Chạy:  python tools/make_manual.py  -> docs/HUONG_DAN_VAN_HANH.pdf
Các bảng hạn mức / kịch bản / endpoint được lấy trực tiếp từ mã nguồn để luôn khớp hệ thống."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("AGENTMON_DB", "/tmp/_manual.db")
os.environ.setdefault("SECRET_KEY", "manual-build-secret-key-0123456789abcdef")

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle, Preformatted)

FD = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DV", FD + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DV-B", FD + "DejaVuSans-Bold.ttf"))
pdfmetrics.registerFont(TTFont("DV-I", FD + "DejaVuSans-Oblique.ttf"))
pdfmetrics.registerFont(TTFont("DV-M", FD + "DejaVuSansMono.ttf"))
from reportlab.pdfbase.pdfmetrics import registerFontFamily
registerFontFamily("DV", normal="DV", bold="DV-B", italic="DV-I", boldItalic="DV-B")

NAVY, BLUE, GREY, LIGHT = colors.HexColor("#0f2742"), colors.HexColor("#1d6fd1"), colors.HexColor("#5b6773"), colors.HexColor("#eef3f9")
S = {
    "title": ParagraphStyle("t", fontName="DV-B", fontSize=26, leading=32, textColor=NAVY, alignment=TA_CENTER),
    "sub": ParagraphStyle("s", fontName="DV", fontSize=12.5, leading=18, textColor=GREY, alignment=TA_CENTER),
    "h1": ParagraphStyle("h1", fontName="DV-B", fontSize=16, leading=21, textColor=NAVY, spaceBefore=6, spaceAfter=8),
    "h2": ParagraphStyle("h2", fontName="DV-B", fontSize=12, leading=16, textColor=BLUE, spaceBefore=10, spaceAfter=4),
    "p": ParagraphStyle("p", fontName="DV", fontSize=9.4, leading=14, spaceAfter=5),
    "b": ParagraphStyle("b", fontName="DV", fontSize=9.4, leading=13.5, leftIndent=14, bulletIndent=3, spaceAfter=2),
    "c": ParagraphStyle("c", fontName="DV", fontSize=8, leading=10.5),
    "ch": ParagraphStyle("ch", fontName="DV-B", fontSize=8, leading=10.5, textColor=colors.white),
    "note": ParagraphStyle("n", fontName="DV", fontSize=9, leading=13, backColor=LIGHT, borderPadding=6, spaceBefore=4, spaceAfter=8, leftIndent=6, rightIndent=6),
    "code": ParagraphStyle("code", fontName="DV-M", fontSize=7.4, leading=9.6, backColor=colors.HexColor("#f4f4f4"), borderPadding=5, spaceAfter=6),
}
W = A4[0] - 3.6 * cm
story = []


def H1(t): story.append(Paragraph(t, S["h1"]))
def H2(t): story.append(Paragraph(t, S["h2"]))
def P(t): story.append(Paragraph(t, S["p"]))
def NOTE(t): story.append(Paragraph(t, S["note"]))
def B(items):
    for i in items:
        story.append(Paragraph(i, S["b"], bulletText="•"))
    story.append(Spacer(1, 3))
def CODE(t): story.append(Preformatted(t, S["code"]))


def TBL(rows, widths, head=True, zebra=True, small=True):
    data = []
    for ri, r in enumerate(rows):
        data.append([Paragraph(str(c), S["ch"] if (head and ri == 0) else S["c"]) for c in r])
    t = Table(data, colWidths=[w * W for w in widths], repeatRows=1 if head else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#c8d1db")), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4), ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if head:
        st.append(("BACKGROUND", (0, 0), (-1, 0), NAVY))
    if zebra:
        for i in range(1, len(rows)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(st))
    story.append(t)
    story.append(Spacer(1, 8))


def box(d, x, y, w, h, text, fill, tc=colors.white, size=8.3, lines=None):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=colors.HexColor("#33475b"), strokeWidth=0.7))
    ls = lines or [text]
    top = y + h / 2 + (len(ls) - 1) * 5.2 + (-3)
    for i, l in enumerate(ls):
        d.add(String(x + w / 2, top - i * 10.4, l, fontName="DV-B" if i == 0 else "DV", fontSize=size if i == 0 else size - 1, fillColor=tc, textAnchor="middle"))


def arrow(d, x1, y1, x2, y2):
    d.add(Line(x1, y1, x2, y2, strokeColor=colors.HexColor("#33475b"), strokeWidth=1.1))
    if abs(x1 - x2) < 1:
        d.add(Polygon([x2 - 3.5, y2 + (6 if y2 < y1 else -6), x2 + 3.5, y2 + (6 if y2 < y1 else -6), x2, y2], fillColor=colors.HexColor("#33475b"), strokeColor=None))
    else:
        d.add(Polygon([x2 + (-6 if x2 > x1 else 6), y2 - 3.5, x2 + (-6 if x2 > x1 else 6), y2 + 3.5, x2, y2], fillColor=colors.HexColor("#33475b"), strokeColor=None))


def pipeline_diagram():
    d = Drawing(W, 330)
    cx, bw = W / 2, W - 20
    steps = [
        ("AI Agent gửi giao dịch", "POST /agent-api/v1/monitor/action (API key)  hoặc  Test Lab", colors.HexColor("#4b5d73")),
        ("1. Hard Policy Check", "pháp lý Agent · hạn mức TSC→CN→KH · số dư · PCI · MCC/quốc gia · kill-switch → vi phạm = BLOCK", colors.HexColor("#a12b35")),
        ("2. Feature Engineering", "hành vi riêng từng KH · velocity/anti-bot · yếu tố mới lạ (người nhận, merchant, quốc gia)", colors.HexColor("#1d6fd1")),
        ("3. Isolation Forest", "điểm bất thường 0–1 (mô hình riêng FX và Thanh toán)", colors.HexColor("#1d6fd1")),
        ("4. LLM Critic (Groq)", "chỉ NÂNG mức rủi ro + giải thích tiếng Việt; lỗi → bộ phản biện luật", colors.HexColor("#6a3fb0")),
        ("5. Quyết định", "ALLOW  |  KYA (KH xác nhận Authenticator)  |  REVIEW (CN duyệt)  |  BLOCK", colors.HexColor("#1f8a5b")),
        ("6. Lưu CSDL + hạch toán + trả kết quả", "chỉ thực hiện khi ALLOW / KYA được duyệt / REVIEW được duyệt", colors.HexColor("#4b5d73")),
    ]
    h, gap, y = 36, 8, 330 - 40
    for i, (t, sub, col) in enumerate(steps):
        box(d, cx - bw / 2, y, bw, h, t, col, lines=[t, sub], size=8.6)
        if i < len(steps) - 1:
            arrow(d, cx, y, cx, y - gap)
        y -= h + gap
    return d


def kya_diagram():
    d = Drawing(W, 215)
    cols = [("AI Agent", 45), ("Hệ thống Monitor", 235), ("Khách hàng / Authenticator", W - 70)]
    for name, x in cols:
        d.add(String(x, 200, name, fontName="DV-B", fontSize=8.5, textAnchor="middle", fillColor=NAVY))
        d.add(Line(x, 190, x, 8, strokeColor=colors.HexColor("#9aa7b4"), strokeDashArray=[3, 3]))
    msgs = [(0, 1, 172, "1. gửi giao dịch"), (1, 1, 154, "2. chấm điểm → KYA, giữ chỗ số dư"), (1, 2, 134, "3. đẩy yêu cầu xác minh (PUSH / TOTP)"),
            (2, 2, 114, "4. KH xem chi tiết, duyệt bằng PIN / OTP"), (2, 1, 94, "5. duyệt / từ chối"), (1, 1, 74, "6. hạch toán và lưu kết quả"),
            (0, 1, 54, "7. Agent hỏi trạng thái"), (1, 0, 34, "8. EXECUTED / DENIED / EXPIRED")]
    for a, b, y, t in msgs:
        xa, xb = cols[a][1], cols[b][1]
        if a == b:
            if a == 2:
                d.add(String(xa - 6, y, t, fontName="DV", fontSize=7.4, textAnchor="end", fillColor=colors.HexColor("#1d3b5c")))
            else:
                d.add(String(xa + 8, y, t, fontName="DV", fontSize=7.4, fillColor=colors.HexColor("#1d3b5c")))
        else:
            arrow(d, xa, y, xb, y)
            d.add(String((xa + xb) / 2, y + 3, t, fontName="DV", fontSize=7.4, textAnchor="middle", fillColor=colors.HexColor("#1d3b5c")))
    return d


def hier_diagram():
    d = Drawing(W, 120)
    w = (W - 30) / 3
    for i, (t, s, c) in enumerate([("TSC – trần theo phân khúc", "STANDARD / VIP / CORPORATE", "#a12b35"), ("Chi nhánh – hạn mức từng CIF", "≤ trần TSC (CN_ADMIN)", "#1d6fd1"), ("Khách hàng – hạn mức Agent", "≤ hạn mức CN; chỉ được HẠ", "#1f8a5b")]):
        box(d, i * (w + 15), 40, w, 60, t, colors.HexColor(c), lines=[t, s], size=8.4)
        if i < 2:
            arrow(d, i * (w + 15) + w, 70, (i + 1) * (w + 15), 70)
    d.add(String(W / 2, 20, "Hạn mức hiệu lực = MIN(TSC, Chi nhánh, Agent)  –  hard policy dùng giá trị này, ML/LLM không ghi đè", fontName="DV-B", fontSize=8.4, textAnchor="middle", fillColor=NAVY))
    return d


# ====================================================================== NỘI DUNG
from agentmon import lab, policy

story.append(Spacer(1, 3.2 * cm))
story.append(Paragraph("AI AGENT MONITOR", S["title"]))
story.append(Paragraph("tích hợp Anti-Bot Pro", S["title"]))
story.append(Spacer(1, 0.6 * cm))
story.append(Paragraph("Hệ thống giám sát AI Agent giao dịch FX và thanh toán<br/>(chuyển tiền · mua sắm online · thẻ Visa / Mastercard)", S["sub"]))
story.append(Spacer(1, 0.5 * cm))
story.append(Paragraph("Tài liệu nguyên tắc thiết kế và hướng dẫn vận hành chi tiết", S["sub"]))
story.append(Spacer(1, 1.6 * cm))
TBL([["Thành phần", "Nội dung"],
     ["Nền tảng", "Anti-Bot Pro v2 (Flask) – đăng nhập, phiên, CSRF, rate-limit, 3 cổng TSC / Chi nhánh / Khách hàng"],
     ["Module mới", "agentmon – 2 phân hệ độc lập: FX Trading và Thanh toán; Isolation Forest; LLM Critic (Groq); KYA/Authenticator; Test Lab"],
     ["Phiên bản", "1.0 (demo/pilot) – 82 test tự động đạt (62 gốc + 20 mới)"],
     ["Đối tượng đọc", "Quản trị TSC, quản trị/nhân viên chi nhánh, khách hàng, đội kỹ thuật triển khai"]], [0.22, 0.78])
story.append(PageBreak())

H1("1. Mục tiêu và nguyên tắc cốt lõi")
P("Hệ thống hợp nhất <b>Anti-Bot Pro</b> (bảo vệ đăng nhập/giao dịch, phân quyền TSC → Chi nhánh → Khách hàng) với <b>AI Agent Monitor</b> (giám sát hành vi của phần mềm AI thực hiện giao dịch thay mặt khách hàng) thành <b>một hệ thống duy nhất</b>: một trang đăng nhập, một CSDL phiên, ba cổng theo vai trò, mỗi cổng có thêm các tab AI Agent.")
B(["<b>Hai phân hệ tách biệt:</b> (1) <b>FX Trading</b> – kiểm soát hạn mức giao dịch và hành vi giao dịch; (2) <b>Thanh toán</b> – kiểm soát hạn mức và hành vi chuyển tiền, mua sắm online, thanh toán thẻ Visa/Mastercard. Mỗi phân hệ có chính sách, mô hình ML, tab Monitor và kịch bản test riêng.",
   "<b>Hard policy trước, ML sau:</b> các giới hạn cứng (hạn mức, số dư, pháp lý Agent, PCI) quyết định BLOCK ngay và <b>không thể bị ML/LLM ghi đè</b>.",
   "<b>Hành vi so với chính khách hàng đó:</b> điểm bất thường tính theo lịch sử riêng của từng khách (giá trị, giờ, người nhận, merchant, quốc gia, đòn bẩy…), không dùng ngưỡng chung cho tất cả.",
   "<b>Pháp lý Agent:</b> khách hàng phải <b>đăng ký Agent với ngân hàng</b> (đồng ý điều khoản, có Authenticator); chi nhánh duyệt và đặt hạn mức. Agent chưa duyệt = bị chặn hoàn toàn.",
   "<b>KYA (Know Your Agent) bằng Authenticator:</b> giao dịch bất thường – ví dụ khách chưa từng giao dịch online nay đột ngột giao dịch – được đẩy tới ứng dụng Authenticator để <b>khách duyệt trước khi thực hiện</b>.",
   "<b>Fail-closed:</b> cần KYA mà khách chưa có Authenticator → BLOCK; LLM lỗi → dùng bộ phản biện luật; quá nhiều KYA chờ → BLOCK (chống dội thông báo)."])

H1("2. Kiến trúc và luồng xử lý")
story.append(pipeline_diagram())
P("Mọi giao dịch của Agent đi qua <b>cùng một hàm engine.evaluate()</b> dù đến từ API key (Agent thật) hay từ Test Lab (demo) – nên kết quả test phản ánh đúng hành vi hệ thống thật.")
TBL([["Tầng", "Thành phần", "Vai trò"],
     ["Giao diện", "templates/portal_*.html, static/js/agentmon.js", "Tab AI Agent trong 3 cổng + trang /authenticator"],
     ["API phiên", "/api/agent/*  (agentmon/api.py)", "Dùng chung đăng nhập, CSRF, fingerprint, rate-limit của Anti-Bot; phân quyền theo vai trò và phạm vi KH"],
     ["API Agent", "/agent-api/v1/*  (Bearer API key)", "Cho AI Agent thật; rate-limit riêng; không lộ điểm rủi ro"],
     ["API Authenticator", "/authapp/*  (Bearer device token + PIN)", "Ghép thiết bị, liệt kê và duyệt/từ chối giao dịch chờ KYA"],
     ["Lõi", "engine · policy · features · ml · critic · kya · registry · cards", "Pipeline quyết định, hạn mức phân cấp, đăng ký pháp lý, tuân thủ thẻ"],
     ["Dữ liệu", "SQLite WAL (data/agentmon.db)", "Production: PostgreSQL (cùng schema). Mô hình ML: models/*.joblib"]], [0.17, 0.38, 0.45])

H1("3. Vai trò, phạm vi và tài khoản demo")
TBL([["Vai trò", "Phạm vi dữ liệu", "Quyền chính với AI Agent"],
     ["TSC (HQ)", "Toàn hệ thống", "Đặt chính sách/trần FX và Thanh toán theo phân khúc; ngưỡng KYA/REVIEW/BLOCK; danh sách MCC/quốc gia cấm; kill-switch; huấn luyện lại ML; xem mọi Monitor"],
     ["Admin chi nhánh (CN_ADMIN)", "KH của chi nhánh", "Duyệt/từ chối đăng ký Agent; đặt hạn mức theo CIF (≤ trần TSC); đình chỉ/khôi phục Agent; khóa thẻ; duyệt giao dịch REVIEW; xóa cờ theo dõi"],
     ["Nhân viên (PNV)", "Các KH được phân công", "Xem Monitor và hồ sơ hành vi; duyệt/từ chối hàng chờ REVIEW; không đổi hạn mức, không duyệt đăng ký"],
     ["Khách hàng (CUSTOMER)", "Chỉ chính mình", "Đăng ký Agent; Authenticator; duyệt/từ chối KYA; hạ hạn mức; cấp API key; quản lý thẻ & người nhận tin cậy; Test Lab cho chính mình. Không thấy điểm ML/LLM"]], [0.2, 0.2, 0.6])
TBL([["Tài khoản (mật khẩu demo123)", "Gợi ý dùng"],
     ["hq01", "TSC: chính sách, kill-switch, mô hình"],
     ["admin_cn01 / admin_cn02", "Admin CN001 (CUST001,003,004,005,008) / CN002 (CUST002,006,007,009,010)"],
     ["staff01 (CUST001, CUST003) · staff02 · staff03", "Nhân viên chi nhánh – duyệt REVIEW"],
     ["cust001", "VIP – FX Agent + Payment Agent đang hoạt động (kịch bản FX-xx, PAY-xx chuẩn)"],
     ["cust002", "Doanh nghiệp – Treasury Bot FX+PAY (CN002)"],
     ["cust003", "Chuẩn – tài khoản ngủ đông 110+ ngày (kịch bản PAY-07)"],
     ["cust004", "Chuẩn – chỉ có lịch sử quầy, chưa từng online; Agent đang PENDING (luồng đăng ký + FIRST_ONLINE)"],
     ["cust005", "VIP – Quant Bot FX+PAY, đòn bẩy cao"]], [0.35, 0.65])


H1("4. Phân hệ FX Trading – nguyên tắc kiểm soát")
P("Agent gửi lệnh FX: <font name='DV-M'>domain=FX, kind=FX_TRADE, pair, side, notional_usd, leverage</font>. Quy đổi VND theo tỷ giá tham chiếu USD/VND trong chính sách (mặc định 26.200).")
H2("4.1 Hard policy (BLOCK ngay, không ML)")
B(["Kill-switch TSC đang bật; Agent chưa đăng ký / PENDING / REJECTED / bị đình chỉ / KH tạm dừng / thu hồi / hết hạn hiệu lực.",
   "Agent không được đăng ký cho FX; CIF không ACTIVE hoặc chưa được chi nhánh bật dịch vụ online.",
   "Cặp tiền ngoài danh mục được phép (giao của TSC phân khúc ∩ CN ∩ Agent).",
   "Đòn bẩy vượt trần; giá trị lệnh vượt hạn mức/lệnh; cộng dồn trong ngày vượt hạn mức ngày (tính cả lệnh đang chờ KYA/REVIEW).",
   "Vượt số lệnh/giờ hoặc /ngày; ngoài khung giờ Agent được phép (nếu cấu hình).",
   "<b>Ký quỹ (notional ÷ đòn bẩy) vượt số dư tiền gửi thanh toán khả dụng</b> – số dư khả dụng đã trừ phần giữ chỗ cho giao dịch chờ."])
H2("4.2 Hành vi giao dịch được chấm điểm")
B(["Giá trị so với trung bình lịch sử của chính khách (tỷ lệ, z-score); giờ lệch thói quen; cặp tiền chưa từng giao dịch; đòn bẩy tăng đột biến so với thói quen.",
   "Velocity/anti-bot: số lệnh trong 5 phút/giờ/24h, nhịp gửi lệnh đều bất thường, lệnh sát trần hạn mức, đã bị chặn nhiều lần.",
   "Dùng quá 70% số dư khả dụng; tài khoản ngủ đông; khách chưa từng giao dịch online/agent; Agent đang thử việc (3 giao dịch đầu luôn cần KYA)."])

H1("5. Phân hệ Thanh toán – nguyên tắc kiểm soát")
P("Ba loại giao dịch: <b>TRANSFER</b> (chuyển tiền), <b>ONLINE_PURCHASE</b> (mua sắm online – CNP), <b>CARD_PAYMENT</b> (thanh toán thẻ). Agent chỉ gửi <b>token thẻ</b> do ngân hàng cấp.")
H2("5.1 Hard policy")
B(["Pháp lý Agent, kill-switch, CIF online (như FX); Agent phải được đăng ký cho đúng loại giao dịch.",
   "<b>Vượt số dư tiền gửi thanh toán khả dụng</b> → BLOCK (hành vi rút vượt số dư).",
   "Chuyển tiền: vượt hạn mức/lần, /ngày, /tháng; tài khoản thụ hưởng trong danh sách chặn.",
   "Thẻ/online: token không hợp lệ hoặc không thuộc khách; thẻ không ACTIVE/hết hạn; thẻ chưa bật online (CNP) hoặc quốc tế; vượt hạn mức thẻ/GD và /ngày; vượt hạn mức thanh toán thẻ/ngày của KH; MCC bị cấm (mặc định 7995 cờ bạc, 6051 tiền mã hóa/quasi-cash); quốc gia bị cấm vận.",
   "<b>PCI-DSS:</b> payload chứa số thẻ đầy đủ (dãy 13–19 số qua Luhn) hoặc trường nhạy cảm (cvv/cvc/pin/track…) → BLOCK + che dữ liệu trước khi lưu/ghi log."])
H2("5.2 Quy định số thẻ Visa / Mastercard (mô phỏng PCI-DSS)")
TBL([["Quy tắc", "Cách hệ thống thực thi"],
     ["Nhận dạng mạng thẻ", "Visa: bắt đầu bằng 4, dài 13/16/19. Mastercard: 51–55 hoặc 2221–2720, dài 16. Mạng khác bị từ chối."],
     ["Kiểm tra Luhn", "Sai Luhn → từ chối đăng ký thẻ"],
     ["Không lưu PAN", "Chỉ lưu BIN6 + 4 số cuối + token + băm HMAC (chống trùng thẻ). PAN bị hủy ngay sau khi token hóa"],
     ["Che số khi hiển thị", "Tối đa 6 đầu + 4 cuối, ví dụ 4111 11** **** 1111"],
     ["Không bao giờ nhận CVV/PIN", "Trường nhạy cảm trong payload của Agent bị chặn và thay bằng [REDACTED]"],
     ["Token hóa", "Agent dùng token (tok_…) – lộ token không lộ số thẻ; chỉ dùng được với đúng KH và đúng trạng thái thẻ"],
     ["3-D Secure", "CNP không 3DS và giá trị ≥ ngưỡng (mặc định 5 triệu) → bắt buộc KYA"],
     ["Dải test", "Demo dùng số thẻ test: 4111111111111111, 4242424242424242, 5555555555554444, 5105105105105100, 2223003122003222"]], [0.25, 0.75])
H2("5.3 Hành vi được chấm điểm")
B(["Người thụ hưởng mới; merchant mới; quốc gia mới hoặc rủi ro cao; MCC rủi ro cao; CNP không 3DS; giá trị gấp nhiều lần mức trung bình <i>của loại giao dịch đó</i> (chuyển khoản và thẻ có baseline riêng).",
   "Dò thẻ (card testing): ≥5 giao dịch &lt; 50.000đ trong 10 phút; tách nhỏ/né hạn mức (số tiền 90–99,9% hạn mức); số tiền tròn triệu bất thường; rút ≥70% số dư; tài khoản ngủ đông; khách lần đầu online."])


H1("6. Hạn mức phân cấp TSC → Chi nhánh → Khách hàng")
story.append(hier_diagram())
P("Giống mô hình cấu hình của Anti-Bot: TSC đặt <b>trần theo phân khúc</b>; Admin chi nhánh đặt <b>hạn mức từng CIF</b> (không được vượt trần – hệ thống từ chối với mã LIMIT_EXCEEDS_TSC); khách hàng đề nghị hạn mức khi đăng ký Agent (chi nhánh duyệt và hệ thống tự kẹp ≤ trần) và sau đó <b>chỉ được hạ</b>, muốn nâng phải qua chi nhánh. Thay đổi trần của TSC có hiệu lực ngay cho hạn mức hiệu lực.")
pf, pp = policy.DEFAULT_FX, policy.DEFAULT_PAY
H2("6.1 Trần mặc định FX")
segs = ["STANDARD", "VIP", "CORPORATE"]
rows = [["Chỉ tiêu"] + segs]
for k in policy.NUM_KEYS["FX"]:
    rows.append([policy.LABELS[k]] + [f"{pf['segments'][s][k]:,.0f}" for s in segs])
rows.append(["Cặp được phép"] + [", ".join(pf["segments"][s]["allowed_pairs"]) if len(pf["segments"][s]["allowed_pairs"]) < 8 else "11 cặp (toàn bộ)" for s in segs])
TBL(rows, [0.34, 0.22, 0.22, 0.22])
H2("6.2 Trần mặc định Thanh toán (VND)")
rows = [["Chỉ tiêu"] + segs]
for k in policy.NUM_KEYS["PAY"]:
    rows.append([policy.LABELS[k]] + [f"{pp['segments'][s][k]:,.0f}" for s in segs])
TBL(rows, [0.34, 0.22, 0.22, 0.22])
g = pp["global"]
H2("6.3 Tham số chung")
TBL([["Tham số", "Mặc định", "Ý nghĩa"],
     ["kya_threshold / review_threshold / block_threshold", f"{g['kya_threshold']} / {g['review_threshold']} / {g['block_threshold']}", "Điểm rủi ro tổng hợp từ ngưỡng nào thì KYA / REVIEW / BLOCK (phải tăng dần)"],
     ["kya_ttl_seconds", str(g["kya_ttl_seconds"]), "Thời gian khách có để duyệt KYA; quá hạn → giao dịch bị hủy, không thực hiện"],
     ["max_pending_kya", str(g["max_pending_kya"]), "Số KYA chờ tối đa/KH; vượt → BLOCK (chống dội thông báo)"],
     ["probation_actions", str(g["probation_actions"]), "Số giao dịch đầu của Agent mới luôn cần KYA"],
     ["dormant_days", str(g["dormant_days"]), "Số ngày không hoạt động để coi là ngủ đông"],
     ["balance_drain_pct", str(g["balance_drain_pct"]), "Giao dịch dùng ≥ tỷ lệ này của số dư khả dụng → KYA"],
     ["cnp_3ds_above_vnd", f"{g['cnp_3ds_above_vnd']:,}", "CNP không 3DS từ mức này → KYA"],
     ["blocked_mcc / high_risk_mcc", f"{', '.join(g['blocked_mcc'])} / {', '.join(g['high_risk_mcc'])}", "MCC cấm (BLOCK) / MCC rủi ro (KYA)"],
     ["blocked_countries / high_risk_countries", f"{', '.join(g['blocked_countries'])} / {', '.join(g['high_risk_countries'])}", "Danh sách mẫu để demo – cấu hình theo chính sách tuân thủ thật của ngân hàng"]], [0.34, 0.26, 0.40])

H1("7. Chấm điểm và quyết định")
P("Sau khi qua hard policy, hệ thống tính ba điểm 0–1 rồi hợp nhất:")
CODE("anomaly   = Isolation Forest (chuẩn hóa theo phân vị 50% → 99,5% của dữ liệu huấn luyện)\n"
     "behavior  = tổng điểm lệch hành vi so với lịch sử RIÊNG của khách (có giải thích từng lý do)\n"
     "velocity  = tổng điểm tốc độ/anti-bot (burst, dò thẻ, né hạn mức, bị chặn nhiều lần)\n"
     "raw   = 0,40·anomaly + 0,30·behavior + 0,30·velocity\n"
     "final = 0,70·raw + 0,30·max(behavior, velocity)      (+0,10 nếu KH đang trong watchlist)\n"
     "# ML đơn độc không kéo điểm lên – cần tín hiệu hành vi/velocity đồng thuận")
TBL([["Điều kiện (xét theo thứ tự)", "Quyết định", "Hệ quả"],
     ["Vi phạm hard policy", "BLOCK", "Không thực hiện; lý do hiển thị cho KH/Agent"],
     ["final ≥ block_threshold", "BLOCK", "Không thực hiện; tăng suspicion của KH"],
     ["final ≥ review_threshold", "REVIEW", "Giữ chỗ số dư; chờ nhân viên CN duyệt/từ chối"],
     ["final ≥ kya_threshold <b>hoặc</b> có trigger KYA", "KYA", "Gửi Authenticator; chỉ thực hiện khi KH duyệt trong thời hạn"],
     ["Còn lại", "ALLOW", "Thực hiện ngay, trừ số dư"],
     ["LLM Critic khuyến nghị cao hơn", "Nâng 1 mức (tối đa REVIEW)", "LLM không bao giờ hạ mức, không tạo BLOCK, không ghi đè hard policy"]], [0.42, 0.18, 0.40])
H2("Trigger bắt buộc KYA (xác định, không phụ thuộc ML)")
TBL([["Mã", "Điều kiện"],
     ["FIRST_ONLINE", "Khách chưa từng có giao dịch online/agent đã thực hiện – nay phát sinh lần đầu"],
     ["DORMANT_WAKE", "Không giao dịch ≥ dormant_days rồi bỗng giao dịch"],
     ["AMOUNT_OVER_KYA", "Giá trị ≥ ngưỡng 'cần KYA' hiệu lực"],
     ["NEW_BENEFICIARY", "Người nhận mới (chưa từng chuyển, chưa trong danh sách tin cậy) và số tiền ≥ ngưỡng người nhận mới"],
     ["NO_3DS / NEW_COUNTRY / HIGH_RISK_COUNTRY / HIGH_RISK_MCC", "Thẻ: không 3DS vượt ngưỡng, quốc gia mới hoặc rủi ro, ngành hàng rủi ro"],
     ["BALANCE_DRAIN", "Dùng ≥ 70% số dư khả dụng"],
     ["LEVERAGE_SPIKE", "FX: đòn bẩy > 10x và gấp > 2,5 lần thói quen"],
     ["AGENT_PROBATION", "Agent mới: N giao dịch đầu"],
     ["CARD_TESTING", "≥5 giao dịch rất nhỏ trong 10 phút"]], [0.36, 0.64])
H2("Mô hình ML")
P("Hai mô hình Isolation Forest (FX: 21 đặc trưng; Thanh toán: 31 đặc trưng) được huấn luyện trên dữ liệu tổng hợp (≈9.000 mẫu/mô hình, 40% khách giả lập là 'mới lên online', có hành vi lành tính hiếm gặp như người nhận mới, số tiền tròn) <b>bằng chính hàm feature của hệ thống</b>. Với khách bình thường, kiểm tra hiệu chỉnh cho thấy ≈ 97% giao dịch đúng thói quen được ALLOW. Trong production cần huấn luyện lại bằng lịch sử thật (HQ → tab Model &amp; LLM, hoặc <font name='DV-M'>python -m agentmon.train_cli</font>).")


H1("8. Đăng ký Agent (pháp lý) và KYA / Authenticator")
H2("8.1 Vòng đời đăng ký Agent")
TBL([["Bước", "Ai", "Nội dung"],
     ["1", "Khách hàng", "Tab 'Authenticator &amp; KYA': tạo mã ghép nối + secret TOTP (điều kiện bắt buộc)"],
     ["2", "Khách hàng", "Tab 'AI Agent của tôi': khai tên, mục đích, nghiệp vụ (FX/PAY), hạn mức đề nghị; <b>đọc và tích đồng ý điều khoản pháp lý</b>; nhập OTP → hồ sơ PENDING (lưu phiên bản điều khoản, thời điểm, IP, mã băm điều khoản)"],
     ["3", "Admin CN", "Tab 'Duyệt Agent': duyệt (đặt hạn mức, tự kẹp ≤ trần TSC) hoặc từ chối kèm lý do → ACTIVE (hiệu lực mặc định 365 ngày)"],
     ["4", "Khách hàng", "Tự cấp API key (cần OTP) – hiển thị một lần; cấp lại sẽ vô hiệu khóa cũ. Admin CN không bao giờ thấy khóa"],
     ["5", "Agent", "Gọi API bằng Bearer key; 3 giao dịch đầu cần KYA (thử việc)"],
     ["6", "Mọi bên", "Tạm dừng (KH), đình chỉ/thu hồi (CN/TSC). KH từ chối KYA 3 lần → hệ thống tự đình chỉ Agent"]], [0.07, 0.15, 0.78])
NOTE("Trạng thái Agent: PENDING → ACTIVE ⇄ PAUSED (KH) / SUSPENDED (ngân hàng) → REVOKED (vĩnh viễn). Bị REJECTED nếu CN từ chối. Chỉ ACTIVE và còn hiệu lực mới được giao dịch.")
H2("8.2 Luồng KYA")
story.append(kya_diagram())
TBL([["Kênh xác minh", "Cách thực hiện", "Bảo mật"],
     ["PUSH (ứng dụng /authenticator)", "KH mở trang trên điện thoại → nhập mã ghép 8 số (hết hạn 10 phút, dùng 1 lần) và đặt PIN thiết bị. Từ đó trang tự hiện giao dịch chờ (3 giây/lần) → Duyệt (nhập PIN) hoặc Từ chối", "Device token lưu băm; PIN lưu băm; sai PIN 5 lần khóa thiết bị 15 phút; chống dò mã ghép theo IP"],
     ["TOTP (Google/Microsoft Authenticator)", "Nhập secret TOTP đã cấp vào ứng dụng; trong tab KYA nhập mã 6 số cạnh giao dịch chờ", "RFC 6238, mã không dùng lại (chống replay), sai 3 lần hủy giao dịch"]], [0.22, 0.48, 0.30])
P("Giao dịch KYA hiển thị cho khách: loại giao dịch, số tiền, người nhận (che còn 4 số cuối), merchant/quốc gia, Agent nào gửi, <b>lý do cần xác minh</b> và thời gian còn lại. Duyệt → hạch toán; Từ chối/hết hạn → không thực hiện, số dư giữ chỗ được nhả.")


H1("9. Hướng dẫn vận hành từng cổng")
H2("9.1 Cổng Khách hàng (/portal/kh)")
TBL([["Tab", "Chức năng"],
     ["Giao dịch FX", "Báo giá và giao dịch FX thủ công của Anti-Bot (giữ nguyên)"],
     ["AI Agent của tôi", "Đăng ký Agent (kèm điều khoản); xem trạng thái, hạn mức hiệu lực; tạm dừng/khôi phục/thu hồi; hạ hạn mức; cấp API key"],
     ["Authenticator &amp; KYA", "Đăng ký TOTP, mã ghép thiết bị; danh sách giao dịch chờ xác minh (tự làm mới) – nhập OTP để Duyệt hoặc Từ chối. Ở demo hiển thị OTP hiện tại để thử nhanh"],
     ["Thẻ &amp; Người nhận", "Thêm thẻ test (kiểm tra Luhn/mạng), token cho Agent, bật/tắt online & quốc tế, khóa tạm; danh sách người nhận tin cậy"],
     ["Monitor FX / Thanh toán", "KPI 90 ngày, biểu đồ quyết định theo ngày, lịch sử giao dịch kèm lý do (KH không thấy điểm ML)"],
     ["Test Lab", "Chạy kịch bản hoặc tự soạn giao dịch như một Agent cho chính mình; nạp số dư demo"]], [0.22, 0.78])
H2("9.2 Cổng Chi nhánh (/portal/cn) – Admin và Nhân viên")
TBL([["Tab", "Chức năng"],
     ["Báo giá FX", "Cấu hình giá/biên lợi nhuận của Anti-Bot (giữ nguyên)"],
     ["Duyệt Agent", "Hồ sơ đăng ký chờ duyệt (admin: nhập hạn mức, Duyệt/Từ chối; Đình chỉ/Khôi phục/Thu hồi Agent)"],
     ["Hạn mức Agent", "Chọn KH → bảng Trần TSC | Hạn mức CN (nhập) | Hiệu lực cho FX và Thanh toán; vượt trần bị từ chối"],
     ["Hàng chờ duyệt", "Giao dịch REVIEW: chi tiết, điểm, lý do, nhận xét LLM → Duyệt &amp; thực hiện / Từ chối (ghi người duyệt + ghi chú)"],
     ["Monitor FX / Thanh toán", "Dashboard + lịch sử đầy đủ điểm ML/Hành vi/Velocity, lý do, LLM; chọn KH hoặc 'xem toàn bộ phạm vi'"],
     ["Thẻ Visa/MC", "Danh sách thẻ che số; khóa tạm/khóa hẳn (admin)"],
     ["Hồ sơ hành vi KH", "Số dư, suspicion/watchlist, lịch sử online, thói quen FX & Thanh toán; xóa cờ theo dõi (admin)"],
     ["Test Lab", "Chạy kịch bản thay mặt KH trong phạm vi"]], [0.22, 0.78])
H2("9.3 Cổng TSC (/portal/hq)")
TBL([["Tab", "Chức năng"],
     ["Giá FX", "Cấu hình giá/biên toàn hệ thống của Anti-Bot (giữ nguyên)"],
     ["Chính sách FX Agent", "Ngưỡng điểm, TTL KYA, tỷ giá tham chiếu, trần theo phân khúc, cặp tiền được phép"],
     ["Chính sách Thanh toán", "Ngưỡng điểm, 3DS, MCC/quốc gia/tài khoản bị chặn, trần chuyển tiền/thẻ/online theo phân khúc"],
     ["Monitor FX / Thanh toán", "Giám sát toàn hệ thống; theo KH hoặc toàn bộ"],
     ["Agent &amp; Kill-switch", "Bật/tắt kill-switch (chặn mọi giao dịch Agent kèm lý do, và hủy cả giao dịch đang chờ khi thực hiện); danh sách mọi Agent, đình chỉ/khôi phục"],
     ["Model &amp; LLM", "Trạng thái 2 mô hình, trạng thái LLM (Groq hay luật), huấn luyện lại, đặt lại dữ liệu demo"],
     ["Test Lab", "Chạy kịch bản cho mọi khách"]], [0.22, 0.78])


H1("10. Test Lab – kịch bản kiểm thử toàn bộ pipeline")
P("Test Lab chạy giao dịch qua <b>đúng engine thật</b> và ghi vào CSDL (nguồn LAB). Mỗi lần chạy kịch bản, Lab tự <b>lưu trữ kết quả lab cũ</b> (không tính vào hạn mức/velocity/baseline), hủy KYA lab đang chờ, xóa cờ theo dõi và khôi phục số dư demo, để kết quả lặp lại được. Có thể 'tự soạn giao dịch' bằng JSON và chọn giờ giả lập (0–23).")
rows = [["Mã", "Kịch bản", "Mô tả / cơ chế", "Kỳ vọng"]]
for s in lab.SCEN:
    rows.append([s[0], s[2], s[3], {"MIXED": "Tăng dần"}.get(s[4], s[4])])
TBL(rows, [0.08, 0.24, 0.52, 0.16])
NOTE("<b>Quy trình demo gợi ý đầu-cuối:</b> (1) cust004 → Authenticator: tạo mã ghép + OTP → AI Agent: đăng ký agent-pay mới (hoặc dùng agent-pay-004 đang PENDING) → (2) admin_cn01 → Duyệt Agent → (3) cust004 → cấp API key → gọi API (ví dụ bên dưới) → giao dịch đầu bị KYA (FIRST_ONLINE + thử việc) → (4) mở /authenticator, duyệt bằng PIN → (5) Agent poll thấy EXECUTED → (6) cust001 chạy FX-02, PAY-08 thấy BLOCK → (7) admin_cn01 xem Hàng chờ duyệt, Monitor → (8) hq01 bật kill-switch, chạy lại FX-01 thấy BLOCK.")

H1("11. API tham chiếu")
H2("11.1 API cho AI Agent (không dùng cookie)")
CODE("POST /agent-api/v1/monitor/action\n"
     "Authorization: Bearer agk_<prefix>_<secret>\nContent-Type: application/json\n\n"
     "# FX\n{\"domain\":\"FX\",\"kind\":\"FX_TRADE\",\"pair\":\"USDVND\",\"side\":\"BUY\",\"notional_usd\":15000,\"leverage\":3,\"request_id\":\"abc-1\"}\n\n"
     "# Chuyển tiền\n{\"domain\":\"PAY\",\"kind\":\"TRANSFER\",\"amount_vnd\":3000000,\"beneficiary_account\":\"9871234560\"}\n\n"
     "# Mua sắm online / thẻ (chỉ token thẻ – KHÔNG gửi số thẻ/CVV)\n{\"domain\":\"PAY\",\"kind\":\"ONLINE_PURCHASE\",\"amount_vnd\":2000000,\"card_token\":\"tok_...\",\n \"merchant_id\":\"M300\",\"mcc\":\"5411\",\"country\":\"VN\",\"three_ds\":true}")
CODE("# Phản hồi\n200 {\"action_id\":123,\"decision\":\"KYA\",\"status\":\"PENDING_KYA\",\"message\":\"...\",\"kya\":{\"id\":\"KYA...\",\"expires_in\":180}}\n"
     "200 {\"decision\":\"ALLOW\",\"status\":\"EXECUTED\"}        403 {\"decision\":\"BLOCK\",\"reason\":\"Vượt hạn mức...\"}\n"
     "GET /agent-api/v1/actions/123   -> trạng thái mới nhất (EXECUTED | DENIED_BY_CUSTOMER | EXPIRED ...)\n"
     "Mã lỗi: 400 BAD_REQUEST (payload sai) · 401 UNAUTHORIZED · 429 RATE_LIMITED (120 yêu cầu/phút/Agent)")
P("<b>request_id</b> bảo đảm idempotent: gửi lại cùng request_id trả về đúng kết quả cũ (duplicate=true), không tạo giao dịch thứ hai. Agent <b>không</b> nhận điểm rủi ro hay lý do nội bộ để tránh dò ngưỡng.")
H2("11.2 Danh sách endpoint giao diện (/api/agent, cần đăng nhập + CSRF cho POST)")
try:
    from app import create_app
    app = create_app()
    rules = sorted((str(r), ",".join(sorted(m for m in r.methods if m in ("GET", "POST")))) for r in app.url_map.iter_rules()
                   if str(r).startswith(("/api/agent", "/agent-api", "/authapp", "/authenticator")))
except Exception as e:      # noqa
    rules = []
who = lambda p: ("TSC" if "/hq/" in p else "CN" if "/cn/" in p else "KH" if "/me/" in p else "Agent" if "agent-api" in p else "Authenticator" if ("authapp" in p or "authenticator" in p) else "Mọi vai trò")
rows = [["Endpoint", "Method", "Đối tượng"]] + [[p.replace("<", "&lt;").replace(">", "&gt;"), m, who(p)] for p, m in rules]
TBL(rows, [0.6, 0.14, 0.26])

H1("12. Cơ sở dữ liệu (agentmon.db)")
TBL([["Bảng", "Nội dung chính"],
     ["agents", "Hồ sơ đăng ký pháp lý: chủ sở hữu, nghiệp vụ, loại giao dịch, hạn mức, phiên bản + mã băm điều khoản, thời điểm/IP đồng ý, người duyệt, hiệu lực, băm API key, thử việc, số lần KH từ chối"],
     ["actions", "Mọi giao dịch/ý định của Agent: số tiền, đối tác, điểm ML/hành vi/velocity/tổng, quyết định, trạng thái, lý do, trigger, nhận xét LLM, người duyệt, nguồn (AGENT_API/LAB/SEED). Payload đã che PAN/CVV"],
     ["kya", "Thử thách KYA: thời hạn, số lần thử, phương thức duyệt (PUSH/TOTP/PORTAL), kết quả"],
     ["authenticators", "Secret TOTP, băm mã ghép, băm device token, băm PIN, số lần sai PIN"],
     ["accounts", "Số dư tiền gửi thanh toán của KH (demo)"],
     ["cards", "Thẻ Visa/MC: BIN6, 4 số cuối, token, băm HMAC, hạn mức, trạng thái, cờ online/quốc tế – KHÔNG có PAN"],
     ["policies / limits", "Chính sách TSC (theo domain) / hạn mức chi nhánh theo CIF"],
     ["flags", "suspicion và watchlist theo KH"],
     ["trusted_beneficiaries", "Người nhận tin cậy do KH khai báo"]], [0.22, 0.78])
P("Ngoài ra mọi thao tác nhạy cảm (đăng ký, duyệt, cấp key, ghép Authenticator, kill-switch, duyệt REVIEW, KYA) đều ghi vào <b>audit log</b> của Anti-Bot (JSON Lines → SIEM) kèm người thao tác, IP, mức cảnh báo.")


H1("13. Cài đặt, cấu hình, triển khai")
CODE("cd anti-bot-ai-agent-monitor\npython -m venv .venv && . .venv/bin/activate\npip install -r requirements.txt\ncp .env.example .env        # đặt SECRET_KEY >= 32 ký tự\npython app.py               # http://127.0.0.1:5000   (demo)\n\n"
     "# Chạy test:   pip install -r requirements-dev.txt && pytest tests -q   (82 test)\n"
     "# Huấn luyện lại ML:  python -m agentmon.train_cli\n"
     "# Sinh lại PDF:       python tools/make_manual.py\n"
     "# Production:  gunicorn -w 4 -b 0.0.0.0:8000 'app:create_app()'   (sau reverse proxy TLS)")
TBL([["Biến môi trường", "Ý nghĩa"],
     ["SECRET_KEY", "Bắt buộc, ≥ 32 ký tự (phiên, CSRF)"],
     ["PRICING_ENVIRONMENT", "demo | production. Production tắt Test Lab và nút reseed (trừ khi AGENTMON_LAB=1)"],
     ["AGENTMON_DB", "Đường dẫn SQLite; production dùng PostgreSQL"],
     ["AGENTMON_MODEL_DIR", "Thư mục mô hình .joblib"],
     ["CARD_VAULT_KEY", "Khóa HMAC băm số thẻ – bắt buộc đặt ở production, lưu trong KMS/HSM"],
     ["LLM_PROVIDER / GROQ_API_KEY / LLM_MODEL / LLM_MODE / LLM_TIMEOUT", "Bật Groq (groq) hoặc bộ phản biện luật (mock); chế độ gray | always | off"],
     ["REDIS_URL", "Rate-limit/phiên dùng chung nhiều worker (như Anti-Bot gốc)"]], [0.38, 0.62])
H2("Bật LLM Critic (Groq)")
CODE("LLM_PROVIDER=groq\nGROQ_API_KEY=gsk_...\nLLM_MODEL=llama-3.3-70b-versatile\nLLM_MODE=gray      # gọi ở vùng xám / có trigger; always = mọi giao dịch; off = tắt")
P("Chỉ dữ liệu đã tối thiểu hóa được gửi tới LLM (không PAN, không tên, không số tài khoản, số tiền làm tròn bậc). Không có khóa hoặc Groq lỗi/timeout → tự động dùng bộ phản biện luật; hệ thống vẫn quyết định bình thường.")

H1("14. Bảo mật đã áp dụng")
B(["Phiên/CSRF/rate-limit/chống bot của Anti-Bot áp dụng cho toàn bộ /api/agent; API Agent và Authenticator có xác thực Bearer, rate-limit và khóa IP khi sai khóa nhiều lần.",
   "Phân quyền theo vai trò và phạm vi KH ở mọi endpoint; KH không xem được dữ liệu KH khác; nhân viên chỉ thấy KH được phân công; chỉ Admin duyệt/đổi hạn mức.",
   "API key, device token, PIN, mã ghép: chỉ lưu băm (SHA-256); so sánh hằng thời gian; key hiển thị một lần.",
   "OTP TOTP không dùng lại; thao tác nhạy cảm (đăng ký Agent, cấp key) yêu cầu OTP.",
   "Xử lý đồng thời: engine tuần tự hóa kiểm tra hạn mức + ghi nhận; hạch toán kiểm tra lại số dư/Agent/kill-switch tại thời điểm thực hiện (chống TOCTOU).",
   "Giữ chỗ số dư và hạn mức ngày cho giao dịch chờ KYA/REVIEW để không thể 'né' bằng cách gửi dồn lệnh chờ.",
   "Dữ liệu thẻ: không PAN/CVV trong CSDL, log hay audit; payload được che trước khi lưu.",
   "Giao diện: mọi chuỗi từ server được escape; CSP của Anti-Bot giữ nguyên."])

H1("15. Giới hạn của bản demo và lộ trình lên production")
TBL([["Hạng mục", "Hiện trạng demo", "Cần làm khi production"],
     ["CSDL", "SQLite 1 máy, khóa tiến trình đơn", "PostgreSQL + khóa dòng (SELECT … FOR UPDATE) cho cộng dồn hạn mức/số dư; sao lưu"],
     ["Số dư & hạch toán", "Bảng accounts mô phỏng; FX chỉ giữ ký quỹ", "Tích hợp core banking/ledger, đối soát; mô hình vị thế FX đầy đủ (đóng vị thế, mark-to-market)"],
     ["Thẻ", "Token hóa nội bộ + số thẻ test", "Card vault/HSM đạt PCI-DSS, network tokenization, 3DS thật từ issuer processor"],
     ["Authenticator", "Web giả lập + TOTP; push bằng polling", "Ứng dụng di động thật, push FCM/APNs, sinh trắc học, gắn thiết bị bằng khóa bất đối xứng"],
     ["Pháp lý", "Mẫu điều khoản + lưu bằng chứng đồng ý", "Pháp chế duyệt điều khoản; chữ ký số/eKYC; lưu trữ theo quy định"],
     ["ML", "Huấn luyện trên dữ liệu tổng hợp", "Huấn luyện bằng lịch sử thật + nhãn gian lận; giám sát drift; quy trình phê duyệt mô hình (MRM)"],
     ["Danh sách cấm", "Danh sách MCC/quốc gia/tài khoản mẫu", "Kết nối danh sách trừng phạt/AML chính thức của ngân hàng"],
     ["Giám sát vận hành", "Audit log JSONL", "Đẩy SIEM, cảnh báo webhook, dashboard SLA, RBAC chi tiết, 4-mắt cho thay đổi chính sách TSC"]], [0.17, 0.33, 0.50])
NOTE("Tài liệu và mã nguồn này là hệ thống <b>demo/pilot</b> phục vụ kiểm thử kiến trúc và nghiệp vụ. Số thẻ, danh sách cấm vận, ngưỡng và điều khoản pháp lý chỉ là ví dụ – cần được các bộ phận tuân thủ, pháp chế và an toàn thông tin của ngân hàng thẩm định trước khi dùng với dữ liệu thật.")

H1("Phụ lục A – Cấu trúc thư mục")
CODE("anti-bot-ai-agent-monitor/\n"
     "├── app/                 Anti-Bot gốc (đăng nhập, guard, portal, giao dịch FX, mock_db)\n"
     "├── agentmon/            MODULE AI AGENT MONITOR\n"
     "│   ├── engine.py        pipeline quyết định + hạch toán + review\n"
     "│   ├── policy.py        chính sách TSC, hạn mức CN, hạn mức hiệu lực\n"
     "│   ├── features.py      feature, điểm hành vi, velocity, trigger KYA\n"
     "│   ├── ml.py            Isolation Forest + dữ liệu huấn luyện tổng hợp\n"
     "│   ├── critic.py        LLM Critic (Groq) + bộ phản biện luật\n"
     "│   ├── kya.py           Authenticator, thử thách KYA\n"
     "│   ├── registry.py      đăng ký Agent pháp lý, API key\n"
     "│   ├── cards.py         Visa/MC, Luhn, token hóa, che PAN/CVV\n"
     "│   ├── seed.py          dữ liệu demo (số dư, thẻ, lịch sử, Agent)\n"
     "│   ├── lab.py           kịch bản Test Lab\n"
     "│   ├── api.py           /api/agent/*      agent_api.py  /agent-api, /authapp\n"
     "│   └── reports.py       dashboard, lịch sử, hồ sơ hành vi\n"
     "├── templates/ static/   3 cổng có tab + trang authenticator\n"
     "├── models/              iforest_fx.joblib, iforest_pay.joblib\n"
     "├── tests/               82 test (test_agentmon.py: 20 test mới)\n"
     "├── tools/make_manual.py sinh PDF này\n"
     "└── docs/HUONG_DAN_VAN_HANH.pdf")


def footer(c, d):
    c.saveState()
    c.setFont("DV", 7.5)
    c.setFillColor(GREY)
    c.drawString(1.8 * cm, 1.1 * cm, "AI Agent Monitor tích hợp Anti-Bot Pro – Hướng dẫn nguyên tắc & vận hành")
    c.drawRightString(A4[0] - 1.8 * cm, 1.1 * cm, f"Trang {d.page}")
    c.restoreState()


out = os.path.join(ROOT, "docs", "HUONG_DAN_VAN_HANH.pdf")
os.makedirs(os.path.dirname(out), exist_ok=True)
doc = SimpleDocTemplate(out, pagesize=A4, leftMargin=1.8 * cm, rightMargin=1.8 * cm, topMargin=1.6 * cm, bottomMargin=1.7 * cm,
                        title="AI Agent Monitor tích hợp Anti-Bot Pro – Hướng dẫn nguyên tắc và vận hành", author="AI Agent Monitor")
doc.build(story, onFirstPage=lambda c, d: None, onLaterPages=footer)
print("OK", out)
