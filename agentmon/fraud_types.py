"""Phân loại kiểu gian lận (typology) và phân biệt GIAN LẬN NGHI VẤN với BẤT THƯỜNG CHƯA XÁC MINH.

Nguyên tắc:
  * Đây là lớp GIẢI THÍCH dựa trên luật (rule-based), chạy sau khi đã có quyết định – KHÔNG thay đổi quyết định
    ALLOW/KYA/REVIEW/BLOCK (quyết định do Hard Policy + điểm rủi ro + trigger KYA).
  * Danh mục dưới đây là danh mục ĐỀ XUẤT theo thông lệ ngành (thẻ, thanh toán, FX, AML). Ngân hàng cần đối chiếu với
    danh mục chuẩn của khối phòng chống gian lận rồi chỉnh trong TAXONOMY (mỗi mục có mã ổn định để ánh xạ).
  * Chưa được hiệu chỉnh trên nhãn gian lận thật: nhãn 'FRAUD_SUSPECTED' nghĩa là "có dấu hiệu phù hợp kiểu gian lận X",
    không phải kết luận gian lận.
"""
from agentmon import features as F
from agentmon.constants import CARD_KINDS

# Phân loại cấp cao
FRAUD_SUSPECTED = "FRAUD_SUSPECTED"          # có dấu hiệu gian lận (HIGH, hoặc ≥ 2 dấu hiệu MED)
ANOMALY = "ANOMALY_UNCONFIRMED"              # bất thường, có thể hợp lệ – cần khách xác minh (KYA)
NORMAL = "NORMAL"

GAMBLING_MCC = {"7995", "7801", "7802"}
QUASI_CASH_MCC = {"6051", "6540"}
MONEY_TRANSFER_MCC = {"4829", "6012"}
DIGITAL_RISK_MCC = {"5967", "5816"}

TAXONOMY = {
    "CARD_TESTING": dict(name="Dò thẻ (card testing)", cat="CARD_FRAUD", sev="HIGH",
                         note="Chuỗi giao dịch giá trị rất nhỏ/nhiều merchant để kiểm tra thẻ còn hiệu lực."),
    "ILLEGAL_GAMBLING": dict(name="Cờ bạc / cá cược", cat="POLICY_AML", sev="HIGH",
                             note="MCC thuộc nhóm cờ bạc (7995…). Chặn cứng theo chính sách TSC."),
    "QUASI_CASH_CRYPTO": dict(name="Quasi-cash / tiền mã hóa / ví lưu giá trị", cat="POLICY_AML", sev="MED",
                              note="MCC 6051, 6540 – kênh chuyển giá trị khó truy vết."),
    "FICTITIOUS_PAYMENT": dict(name="Thanh toán khống / ĐVCNT nghi vấn", cat="MERCHANT_FRAUD", sev="MED",
                               note="Heuristic: merchant mới + số tiền lớn/tròn + MCC rủi ro/không 3DS, hoặc lặp lại cùng merchant mới. "
                                    "CẦN dữ liệu rủi ro ĐVCNT (MID, ngày onboard, chargeback) để chính xác."),
    "STRUCTURING": dict(name="Tách nhỏ / né hạn mức (structuring)", cat="AML", sev="MED", note="Số tiền sát trần hạn mức."),
    "ACCOUNT_TAKEOVER": dict(name="Chiếm quyền tài khoản / thông tin xác thực", cat="ATO", sev="HIGH",
                             note="Khách ít/chưa dùng kênh online hoặc ngủ đông + (người nhận/thiết bị/quốc gia mới hoặc rút cạn số dư)."),
    "FUND_DRAIN_MULE": dict(name="Rút cạn số dư / tài khoản trung gian (mule)", cat="ATO_AML", sev="HIGH",
                            note="Dùng ≥ 70% số dư chuyển cho người nhận mới."),
    "CNP_NO_AUTH": dict(name="Gian lận thẻ CNP không xác thực", cat="CARD_FRAUD", sev="MED", note="CNP vượt ngưỡng nhưng không có 3-D Secure."),
    "PCI_EXPOSURE": dict(name="Lộ dữ liệu thẻ (PAN/CVV trong payload)", cat="DATA_SECURITY", sev="HIGH",
                         note="Agent gửi số thẻ/CVV – vi phạm PCI-DSS; dữ liệu đã được che."),
    "SANCTIONS_BLOCKLIST": dict(name="Quốc gia cấm vận / tài khoản trong danh sách chặn", cat="SANCTIONS", sev="HIGH", note="Theo danh sách TSC cấu hình."),
    "HIGH_RISK_GEO": dict(name="Quốc gia rủi ro cao", cat="CARD_FRAUD", sev="MED", note="Theo danh sách TSC cấu hình."),
    "HIGH_RISK_MCC": dict(name="Ngành hàng rủi ro cao", cat="CARD_FRAUD", sev="MED", note="Theo danh sách TSC cấu hình."),
    "WALLET_DEVICE_ABUSE": dict(name="Lạm dụng ví điện tử trên thiết bị lạ", cat="WALLET_FRAUD", sev="MED",
                                note="Thẻ thanh toán qua ví trên thiết bị chưa từng dùng; nâng HIGH nếu số tiền bất thường."),
    "ATM_CASHOUT_ABROAD": dict(name="Rút tiền ATM nước ngoài (cash-out)", cat="CARD_FRAUD", sev="MED",
                               note="ATM ngoài VN; nâng HIGH nếu ngoài giờ hoặc số tiền bất thường."),
    "FX_BOT_BURST": dict(name="Dồn lệnh FX tự động bất thường", cat="AGENT_ABUSE", sev="MED", note="Nhiều lệnh/5 phút hoặc nhịp đều như máy."),
    "FX_LEVERAGE_ABUSE": dict(name="Lạm dụng đòn bẩy FX", cat="AGENT_ABUSE", sev="MED", note="Đòn bẩy tăng đột biến so với thói quen."),
    "OFFHOUR_LARGE": dict(name="Giao dịch lớn ngoài giờ", cat="ATO", sev="MED", note="Gấp > 3 lần thường lệ trong khung 23h–5h."),
    "CROSS_DOMAIN_BURST": dict(name="FX và thanh toán dồn dập đồng thời", cat="AGENT_ABUSE", sev="MED",
                               note="≥ 4 lệnh ở phân hệ khác trong 5 phút: nghi Agent bị điều khiển hoặc rút tiền ngay sau khi giao dịch FX."),
    "SESSION_BOT": dict(name="Phiên người dùng có dấu hiệu bot/tự động", cat="ATO", sev="MED",
                        note="Điểm Anti-Bot của phiên ≥ 70/100; nâng HIGH khi ≥ 90 hoặc kèm thiết bị/người nhận mới."),
    "MULE_COLLECTION": dict(name="Tài khoản trung gian / thu gom tiền (mule)", cat="ATO_AML", sev="MED",
                            note="≥ 3 khách khác chuyển tới cùng người nhận trong 24 giờ; HIGH khi ≥ 5."),
    "ACTOR_CONFLICT": dict(name="Người và Agent cùng thao tác dồn dập", cat="AGENT_ABUSE", sev="MED",
                           note="≥ 3 giao dịch của loại người thực hiện ngược lại trong 10 phút trên cùng tài khoản."),
    "CARD_MANUAL_ENTRY": dict(name="Nhập tay số thẻ / MOTO", cat="CARD_FRAUD", sev="MED", note="Giao dịch không xuất trình thẻ vật lý; rủi ro dùng số thẻ bị lộ."),
    "CARD_SKIMMING": dict(name="Thẻ giả / skimming / chạm không xác thực", cat="CARD_FRAUD", sev="MED", note="Fallback quẹt từ, chạm vượt hạn mức không CVM, thẻ nội địa dùng nước ngoài."),
    "REFUND_ABUSE": dict(name="Lạm dụng hoàn tiền", cat="MERCHANT_FRAUD", sev="MED", note="Hoàn tiền không có giao dịch gốc hoặc về thẻ khác; HIGH khi về thẻ khác."),
    "CARD_MERCHANT_ABUSE": dict(name="Merchant lạm dụng capture/pre-auth", cat="MERCHANT_FRAUD", sev="MED", note="Capture vượt 120% số tiền pre-auth."),
    "QR_SWAP": dict(name="Thay/giả mã QR tĩnh", cat="QR_FRAUD", sev="MED", note="QR tĩnh số tiền lớn tới merchant lạ."),
    "IMPOSSIBLE_TRAVEL": dict(name="Di chuyển bất khả thi", cat="CARD_FRAUD", sev="HIGH", note="Hai giao dịch ở hai quốc gia khác nhau cách nhau < 2 giờ."),
    "ACTOR_SPOOFING": dict(name="Khai báo người thực hiện không khớp quan sát", cat="AGENT_ABUSE", sev="MED",
                           note="Khai báo là người nhưng hành vi tự động (hoặc ngược lại); khóa Agent bị người dùng chung."),
    "ATM_THIRD_PARTY_USE": dict(name="Người khác dùng thẻ tại ATM (khuôn mặt không khớp)", cat="CARD_FRAUD", sev="HIGH", note="Camera AI: khuôn mặt không khớp mẫu đã đăng ký của chủ thẻ."),
    "ATM_SPOOF_ATTACK": dict(name="Giả mạo sinh trắc tại ATM (ảnh/video/mặt nạ/deepfake)", cat="CARD_FRAUD", sev="HIGH", note="Liveness thấp hoặc phát hiện injection/virtual camera (PAD)."),
    "ATM_NO_PERSON": dict(name="Giao dịch ATM không có người trước máy", cat="ATM_ATTACK", sev="HIGH", note="Nghi rút tiền từ xa, relay, malware/jackpotting."),
    "ATM_CAMERA_BLOCKED": dict(name="Che/can thiệp camera ATM", cat="ATM_ATTACK", sev="MED", note="Dấu hiệu chuẩn bị gian lận (skimming, cướp, ép buộc)."),
    "ATM_COERCION_OR_SURFING": dict(name="Nhiều người trước ATM (ép buộc/nhìn trộm PIN)", cat="CARD_FRAUD", sev="MED", note="≥ 2 khuôn mặt trong khung hình."),
    "ATM_CARD_COLLECTION": dict(name="Nhiều thẻ của nhiều chủ trên cùng ATM", cat="CARD_FRAUD", sev="MED", note="≥ 4 chủ thẻ khác nhau trên một ATM trong 10 phút (thu gom thẻ)."),
    "ATM_PIN_AUTOMATED": dict(name="Nhập PIN theo nhịp máy", cat="ATM_ATTACK", sev="MED", note="Hệ số biến thiên khoảng cách phím < 0,05."),
    "AGENT_CASH_OUT": dict(name="AI Agent rút tiền mặt", cat="AGENT_ABUSE", sev="MED", note="ATM là thiết bị vật lý; Agent rút tiền mặt từ xa phải được chủ thẻ xác nhận."),
    "FRAUD_RING": dict(name="Vòng gian lận / tài khoản liên kết (đồ thị)", cat="ATO_AML", sev="MED", note="≥ 4 khách khác liên kết qua thiết bị/người nhận/IP trong 7 ngày; HIGH khi ≥ 6. Gia đình/doanh nghiệp dùng chung thiết bị cũng tạo liên kết."),
    "STATEMENT_ABUSE": dict(name="Lạm dụng thanh toán sao kê (trả thừa rồi rút/hoàn)", cat="CARD_FRAUD", sev="MED", note="Số tiền trả > 120% dư nợ sao kê."),
    "THIRD_PARTY_PAYMENT": dict(name="Người lạ trả nợ thẻ thay (rửa tiền/tài khoản trung gian)", cat="AML", sev="MED", note="Người thanh toán không phải chủ thẻ, số tiền lớn."),
    "CARD_TO_CARD_CASHOUT": dict(name="Thẻ tín dụng trả cho thẻ tín dụng (biến tín dụng thành tiền)", cat="CARD_FRAUD", sev="MED", note="Nguồn tiền là thẻ tín dụng."),
    "PREPAID_ABUSE": dict(name="Nạp thẻ trả trước lớn", cat="AML", sev="MED", note="Nạp trả trước vượt ngưỡng."),
    "AGENT_VELOCITY_ABUSE": dict(name="Agent gửi lệnh dồn dập (velocity)", cat="AGENT_ABUSE", sev="MED", note="Sát trần số lệnh/giờ."),
}
# Bất thường có thể hợp lệ → xử lý bằng KYA
ANOMALY_CODES = {"FIRST_ONLINE", "DORMANT_WAKE", "NEW_BENEFICIARY", "AMOUNT_OVER_KYA", "AGENT_PROBATION", "NEW_COUNTRY",
                 "BALANCE_DRAIN", "NEW_DEVICE", "ATM_FOREIGN", "LINKED_ACCOUNTS", "SUPERVISED_HIGH_RISK", "STATEMENT_OVERPAY", "THIRD_PARTY_PAYER", "CC_FUNDS_CC", "PREPAID_LOAD_HIGH", "ATM_FACE_UNCERTAIN", "ATM_MULTIPLE_FACES", "ATM_NOT_ENROLLED", "ATM_CAMERA_OFFLINE", "ATM_CAMERA_BLOCKED",
                 "ATM_PIN_AUTOMATED", "ATM_CARD_COLLECTION", "AGENT_CASH_OUT", "MULE_RECIPIENT", "SESSION_BOT", "ACTOR_UNVERIFIED", "MANUAL_ENTRY", "CHIP_FALLBACK",
                 "CONTACTLESS_NO_CVM", "REFUND_UNMATCHED", "REFUND_OTHER_CARD", "CAPTURE_OVER_PREAUTH", "DOMESTIC_CARD_ABROAD", "STATIC_QR_HIGH", "IMPOSSIBLE_TRAVEL", "NO_3DS", "HIGH_RISK_COUNTRY", "HIGH_RISK_MCC", "LEVERAGE_SPIKE", "CARD_TESTING"}


def classify(a: dict, ctx, triggers, final_risk=None, pci=False, kya_threshold=0.35) -> dict:
    """Trả {class, types:[{code,name,cat,severity,evidence}], anomaly_codes, handling, basis}."""
    f = F.context_flags(a, ctx)
    g = f["g"]
    kind = a.get("kind")
    amt = f["amt"]
    cap = F._cap(ctx, a)
    tcodes = {t[0] for t in (triggers or [])}
    found = {}

    def add(code, evidence, sev=None):
        meta = TAXONOMY[code]
        found[code] = dict(code=code, name=meta["name"], cat=meta["cat"], severity=sev or meta["sev"], evidence=evidence)

    if pci:
        add("PCI_EXPOSURE", "Payload chứa PAN/CVV/PIN")
    if ctx.domain == "FX":
        lev = float(a.get("leverage") or 1)
        if f["n5"] >= 8:
            add("FX_BOT_BURST", f"{f['n5']} lệnh trong 5 phút", "HIGH")
        elif f["n5"] >= 5 or (f["n1h"] >= 8 and f["cv"] < 0.1):
            add("FX_BOT_BURST", f"{f['n5']} lệnh/5 phút; nhịp đều" if f["cv"] < 0.1 else f"{f['n5']} lệnh trong 5 phút")
        if "LEVERAGE_SPIKE" in tcodes:
            add("FX_LEVERAGE_ABUSE", f"Đòn bẩy {lev:g}x so với thói quen {f['st']['lev_mean']:.1f}x")
    else:
        mcc = a.get("mcc")
        if a.get("beneficiary") in g.get("blocked_accounts", []) or a.get("country") in g.get("blocked_countries", []):
            add("SANCTIONS_BLOCKLIST", f"Quốc gia={a.get('country')}, tài khoản trong danh sách chặn={a.get('beneficiary') in g.get('blocked_accounts', [])}")
        if mcc in GAMBLING_MCC or (mcc in g.get("blocked_mcc", []) and mcc not in QUASI_CASH_MCC):
            add("ILLEGAL_GAMBLING" if mcc in GAMBLING_MCC else "HIGH_RISK_MCC", f"MCC {mcc}")
        if mcc in QUASI_CASH_MCC:
            add("QUASI_CASH_CRYPTO", f"MCC {mcc}")
        elif mcc in g.get("high_risk_mcc", []) and "ILLEGAL_GAMBLING" not in found:
            add("HIGH_RISK_MCC", f"MCC {mcc}")
        if a.get("country") in g.get("high_risk_countries", []):
            add("HIGH_RISK_GEO", f"Quốc gia {a.get('country')}")
        if f["small_burst"] >= 5:
            add("CARD_TESTING", f"{f['small_burst']} giao dịch < 50.000đ trong 10 phút")
        if "NO_3DS" in tcodes:
            add("CNP_NO_AUTH", f"CNP {amt:,.0f} VND không 3DS")
        if kind == "WALLET_PAYMENT" and f["new_device"]:
            add("WALLET_DEVICE_ABUSE", "Thiết bị ví mới", "HIGH" if f["ratio"] >= 3 else None)
        if f["atm_foreign"]:
            add("ATM_CASHOUT_ABROAD", f"ATM tại {a.get('country')}", "HIGH" if (f["off_hour"] or f["ratio"] >= 2) else None)
        new_b = "NEW_BENEFICIARY" in tcodes or (kind == "TRANSFER" and a.get("beneficiary") and a["beneficiary"] not in f["st"]["benef"]
                                                and a["beneficiary"] not in ctx.trusted)
        if f["benef_senders"] >= 3:
            add("MULE_COLLECTION", f"{f['benef_senders']} khách khác chuyển tới cùng người nhận trong 24 giờ", "HIGH" if f["benef_senders"] >= 5 else None)
        if f["bal_pct"] >= g.get("balance_drain_pct", 0.7) and f["bal_pct"] < 1.0:
            if new_b:
                add("FUND_DRAIN_MULE", f"Dùng {min(f['bal_pct'], 1) * 100:.0f}% số dư cho người nhận mới")
        if kind in CARD_KINDS:
            from agentmon import cardmodel
            for _w, msg, _t, ft in cardmodel.signals(a, ctx.hist, g, amt, False):
                if ft and ft in TAXONOMY:
                    add(ft, msg, "HIGH" if (ft == "REFUND_ABUSE" and a.get("refund_to_other_card")) else None)
        if kind in CARD_KINDS and kind != "ATM_WITHDRAWAL":
            new_m = bool(a.get("merchant")) and a["merchant"] not in f["st"]["merch"] and f["st"]["n"] >= 5
            round_amt = amt >= 1_000_000 and amt % 1_000_000 == 0
            repeat = sum(1 for x in ctx.attempts if x.get("merchant") and x.get("merchant") == a.get("merchant")) >= 2
            risky = (a.get("mcc") in g.get("high_risk_mcc", [])) or ("NO_3DS" in tcodes) or (a.get("country") in g.get("high_risk_countries", []))
            if new_m and (round_amt or f["ratio"] >= 3) and risky:
                add("FICTITIOUS_PAYMENT", "Merchant mới + số tiền lớn/tròn + MCC rủi ro/không 3DS")
            elif new_m and repeat and (round_amt or f["ratio"] >= 2):
                add("FICTITIOUS_PAYMENT", "Lặp lại nhiều lần tại merchant mới với số tiền tròn/lớn")
    if 0.90 <= amt / cap < 1.0:
        add("STRUCTURING", f"{amt / cap * 100:.0f}% hạn mức/lần")
    if f["off_hour"] and f["ratio"] > 3:
        add("OFFHOUR_LARGE", f"Gấp {f['ratio']:.1f} lần thường lệ lúc {f['hour']}h")
    for _c, _m, _s in a.get("atm_fraud", []):
        add(_c, _m, _s)
    if a.get("actor_type") == "AGENT" and kind == "ATM_WITHDRAWAL":
        add("AGENT_CASH_OUT", "Agent gửi giao dịch ATM")
    if f["ring_size"] >= 4:
        add("FRAUD_RING", f"{f['ring_size']} khách liên kết qua thiết bị/người nhận/IP", "HIGH" if f["ring_size"] >= 6 else None)
    if a.get("actor_unverified"):
        add("ACTOR_SPOOFING", "Khai báo/quan sát người thực hiện không khớp (Anti-Bot ↔ Monitor)")
    if f["session_risk"] >= 0.7:
        add("SESSION_BOT", f"Anti-Bot {f['session_risk'] * 100:.0f}/100", "HIGH" if (f["session_risk"] >= 0.9 or f["new_device"]) else None)
    if ctx.cross_actor_n10 >= 3:
        add("ACTOR_CONFLICT", f"{ctx.cross_actor_n10} giao dịch của {'người dùng' if ctx.actor == 'AGENT' else 'Agent'} trong 10 phút")
    if getattr(ctx, "cross_n5", 0) >= 4:
        add("CROSS_DOMAIN_BURST", f"{ctx.cross_n5} lệnh ở phân hệ khác trong 5 phút")
    if f["n1h"] >= 0.8 * float(ctx.limits.get("per_hour") or 30):
        add("AGENT_VELOCITY_ABUSE", f"{f['n1h']} lệnh/giờ sát trần")
    # Chiếm quyền: (chưa từng online | ngủ đông) kết hợp một dấu hiệu "đổi hành vi"
    dormant = ctx.last_exec_ts and f["dormant_days"] >= g.get("dormant_days", 60)
    shift = ctx.domain == "PAY" and (("NEW_BENEFICIARY" in tcodes) or f["new_device"] or "NEW_COUNTRY" in tcodes or f["bal_pct"] >= g.get("balance_drain_pct", 0.7))
    if ctx.domain == "PAY" and kind == "TRANSFER" and f["new_device"] and f["ratio"] >= 3 and \
            a.get("beneficiary") and a["beneficiary"] not in f["st"]["benef"] and a["beneficiary"] not in ctx.trusted:
        add("ACCOUNT_TAKEOVER", f"Thiết bị mới + người nhận mới + số tiền gấp {f['ratio']:.1f} lần thường lệ")
    if (f["first_online"] or dormant) and shift:
        add("ACCOUNT_TAKEOVER", "Khách " + ("chưa từng online" if f["first_online"] else f"ngủ đông {int(f['dormant_days'])} ngày") + " + thay đổi hành vi")

    types = sorted(found.values(), key=lambda t: (0 if t["severity"] == "HIGH" else 1, t["code"]))
    high = [t for t in types if t["severity"] == "HIGH"]
    med = [t for t in types if t["severity"] == "MED"]
    anomaly = sorted(tcodes & ANOMALY_CODES)
    if high or len(med) >= 2:
        cls, handling = FRAUD_SUSPECTED, "Không thực hiện tự động: chặn hoặc chuyển nhân viên chi nhánh rà soát; xác minh khách qua kênh độc lập."
    elif med or anomaly or (final_risk is not None and final_risk >= kya_threshold):
        cls, handling = ANOMALY, "Bất thường có thể hợp lệ: yêu cầu khách xác minh (KYA) trước khi thực hiện."
    else:
        cls, handling = NORMAL, "Không có dấu hiệu bất thường."
    return {"class": cls, "types": types, "anomaly_codes": anomaly, "handling": handling,
            "basis": "rule-based (chưa hiệu chỉnh trên nhãn gian lận thật)"}


def markdown() -> str:
    lines = ["# Danh mục kiểu gian lận (Fraud Typology)\n",
             "Sinh tự động từ `agentmon/fraud_types.py`. **Đây là danh mục đề xuất** – cần đối chiếu với danh mục chuẩn của khối phòng chống gian lận.\n",
             "| Mã | Tên | Nhóm | Mức | Ghi chú |", "|---|---|---|---|---|"]
    for c, m in TAXONOMY.items():
        lines.append(f"| `{c}` | {m['name']} | {m['cat']} | {m['sev']} | {m['note']} |")
    lines += ["", "## Phân loại cấp cao\n",
              f"* `{FRAUD_SUSPECTED}` – có ít nhất 1 dấu hiệu HIGH hoặc ≥ 2 dấu hiệu MED.",
              f"* `{ANOMALY}` – bất thường (trigger KYA hoặc điểm ≥ ngưỡng KYA) nhưng chưa đủ dấu hiệu gian lận → khách xác minh.",
              f"* `{NORMAL}` – không có dấu hiệu.", "",
              "Mã bất thường có thể hợp lệ (xử lý bằng KYA): " + ", ".join(f"`{c}`" for c in sorted(ANOMALY_CODES)) + ".", ""]
    return "\n".join(lines)
