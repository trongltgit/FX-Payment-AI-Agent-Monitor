"""Mô hình thẻ & thanh toán (v2): mạng thẻ, sản phẩm thẻ, loại giao dịch thẻ, phương thức nhập thẻ (entry mode), xác thực (CVM),
QR/hóa đơn. Gồm (1) danh mục chuẩn hóa/kiểm tra payload, (2) bộ tín hiệu rủi ro DỰA TRÊN LUẬT riêng cho thẻ.

Lưu ý trung thực: các luật dưới đây theo thông lệ ngành, ngưỡng là GIÁ TRỊ CẤU HÌNH mặc định (policy.global), chưa hiệu chỉnh trên dữ liệu thật;
Agent/hệ thống nguồn chỉ gửi TOKEN thẻ – mạng thẻ lấy từ bin6 của bản ghi thẻ (hoặc payload), không bao giờ từ PAN đầy đủ.
"""
import re

# ---------------------------------------------------------------- danh mục
NETWORKS = {
    "VISA": "Visa", "MASTERCARD": "Mastercard", "JCB": "JCB", "UNIONPAY": "UnionPay", "AMEX": "American Express",
    "DISCOVER_DINERS": "Discover / Diners Club", "NAPAS": "NAPAS (thẻ nội địa)", "OTHER": "Mạng khác",
}
PRODUCTS = {
    "CREDIT": "Thẻ tín dụng", "DEBIT": "Thẻ ghi nợ", "PREPAID": "Thẻ trả trước", "VIRTUAL": "Thẻ ảo (dùng một lần/nhiều lần)",
    "CORPORATE": "Thẻ doanh nghiệp/thương mại", "OTHER": "Khác",
}
# Loại giao dịch thẻ (txn_subtype)
SUBTYPES = {
    "PURCHASE": "Mua hàng", "PREAUTH": "Ủy quyền trước (pre-auth)", "CAPTURE": "Hoàn tất ủy quyền (capture/completion)",
    "REFUND": "Hoàn tiền", "REVERSAL": "Hủy/đảo giao dịch", "CASH_ADVANCE": "Ứng tiền mặt", "QUASI_CASH": "Quasi-cash",
    "RECURRING": "Thanh toán định kỳ", "MOTO": "Đặt hàng qua thư/điện thoại", "INSTALLMENT": "Trả góp",
    "CARD_TO_CARD": "Chuyển tiền thẻ-đến-thẻ", "TOP_UP": "Nạp tiền (ví/trả trước)", "BALANCE_INQUIRY": "Hỏi số dư",
}
# Phương thức nhập thẻ (entry mode)
ENTRY_MODES = {
    "CHIP": "Chip EMV (cắm)", "CONTACTLESS": "Chạm (NFC/contactless)", "MAGSTRIPE": "Quẹt từ", "MANUAL_KEY": "Nhập tay số thẻ",
    "ECOM": "Thương mại điện tử", "WALLET_TOKEN": "Token ví điện tử (Apple/Google/Samsung Pay)", "QR": "Quét mã QR", "MOTO": "Qua thư/điện thoại",
}
# Xác thực chủ thẻ (CVM)
AUTH_METHODS = {"PIN": "PIN", "THREE_DS": "3-D Secure", "OTP": "OTP", "BIOMETRIC": "Sinh trắc", "CDCVM": "Xác thực trên thiết bị (ví)",
                "SIGNATURE": "Chữ ký", "NONE": "Không xác thực"}
# QR / hóa đơn
QR_SCHEMES = {"VIETQR": "VietQR (NAPAS)", "NAPAS_247": "NAPAS 247", "EMVCO_MPM": "EMVCo QR (merchant-presented)", "CARD_SCHEME_QR": "QR của tổ chức thẻ",
               "WALLET_QR": "QR ví điện tử", "OTHER": "Khác"}
QR_TYPES = {"STATIC": "QR tĩnh", "DYNAMIC": "QR động (theo giao dịch)"}

# Tiền tố BIN → mạng thẻ (phát hiện sơ bộ từ bin6; bản ghi thẻ thật nên ghi rõ network)
_BIN_RULES = [
    (r"^4", "VISA"), (r"^(5[1-5]|2[2-7])", "MASTERCARD"), (r"^35(2[89]|[3-8])", "JCB"), (r"^(34|37)", "AMEX"), (r"^62", "UNIONPAY"),
    (r"^(6011|65|64[4-9]|30[0-5]|36|38|39)", "DISCOVER_DINERS"), (r"^(9704|9705)", "NAPAS"),
]


def network_from_bin(bin6: str) -> str:
    b = re.sub(r"\D", "", str(bin6 or ""))
    for pat, net in _BIN_RULES:
        if re.match(pat, b):
            return net
    return "OTHER"


def _enum(raw, key, table, default, name):
    v = raw.get(key)
    if v in (None, ""):
        return default
    v = str(v).upper()
    if v not in table:
        raise ValueError(f"{name} phải là một trong: " + ", ".join(table))
    return v


# Loại giao dịch (kind) → mặc định
_DEFAULT_SUBTYPE = {"ONLINE_PURCHASE": "PURCHASE", "CARD_PAYMENT": "PURCHASE", "ATM_WITHDRAWAL": "CASH_ADVANCE", "WALLET_PAYMENT": "PURCHASE",
                    "BILL_PAYMENT": "PURCHASE", "QR_PAYMENT": "PURCHASE", "CARD_STATEMENT_PAYMENT": "TOP_UP"}
_DEFAULT_ENTRY = {"CARD_PAYMENT": "CHIP", "ONLINE_PURCHASE": "ECOM", "WALLET_PAYMENT": "WALLET_TOKEN", "ATM_WITHDRAWAL": "CHIP", "QR_PAYMENT": "QR",
                  "BILL_PAYMENT": "ECOM", "CARD_STATEMENT_PAYMENT": "ECOM"}


def normalize(raw: dict, kind: str, channel_type, card: dict | None):
    """Chuẩn hóa các trường thẻ mở rộng; ném ValueError nếu giá trị không thuộc danh mục."""
    out = {}
    out["txn_subtype"] = _enum(raw, "txn_subtype", SUBTYPES, _DEFAULT_SUBTYPE.get(kind, "PURCHASE"), "txn_subtype")
    out["entry_mode"] = _enum(raw, "entry_mode", ENTRY_MODES, _DEFAULT_ENTRY.get(kind, "ECOM"), "entry_mode")
    out["auth_method"] = _enum(raw, "auth_method", AUTH_METHODS, None, "auth_method")
    out["card_product"] = _enum(raw, "card_product", PRODUCTS, None, "card_product")
    net = raw.get("card_network")
    if net not in (None, ""):
        net = str(net).upper()
        if net not in NETWORKS:
            raise ValueError("card_network phải là một trong: " + ", ".join(NETWORKS))
    else:
        net = (card or {}).get("network")
        net = str(net).upper() if net else None
        if net not in NETWORKS:
            net = network_from_bin((card or {}).get("bin6") or raw.get("bin6"))
    out["card_network"] = net
    out["chip_fallback"] = bool(raw.get("chip_fallback"))           # thẻ có chip nhưng terminal phải quẹt từ/nhập tay
    out["refund_original_ref"] = (str(raw.get("refund_original_ref"))[:40] if raw.get("refund_original_ref") else None)
    out["refund_to_other_card"] = bool(raw.get("refund_to_other_card"))
    try:
        out["preauth_amount"] = float(raw["preauth_amount"]) if raw.get("preauth_amount") not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("preauth_amount phải là số.")
    if kind == "CARD_STATEMENT_PAYMENT":
        try:
            out["statement_balance"] = float(raw["statement_balance"]) if raw.get("statement_balance") not in (None, "") else None
        except (TypeError, ValueError):
            raise ValueError("statement_balance phải là số.")
        out["payer_is_cardholder"] = bool(raw.get("payer_is_cardholder", True))
        fs = str(raw.get("funding_source_type", "ACCOUNT")).upper()
        if fs not in ("ACCOUNT", "CREDIT_CARD", "CASH", "OTHER"):
            raise ValueError("funding_source_type phải là ACCOUNT, CREDIT_CARD, CASH hoặc OTHER.")
        out["funding_source_type"] = fs
    if kind in ("QR_PAYMENT", "BILL_PAYMENT"):
        out["qr_scheme"] = _enum(raw, "qr_scheme", QR_SCHEMES, "VIETQR" if kind == "QR_PAYMENT" else None, "qr_scheme")
        out["qr_type"] = _enum(raw, "qr_type", QR_TYPES, None, "qr_type")
    return out


# ---------------------------------------------------------------- tín hiệu rủi ro (luật)
def signals(a: dict, hist: list, g: dict, amt: float, new_merchant: bool):
    """Trả danh sách (trọng số hành vi, mô tả, mã trigger|None, mã loại gian lận|None). Chỉ cho giao dịch thẻ."""
    S = []
    em, st, net = a.get("entry_mode"), a.get("txn_subtype"), a.get("card_network")
    auth = a.get("auth_method")
    if em in ("MANUAL_KEY", "MOTO") or st == "MOTO":
        S.append((0.20, "Nhập tay số thẻ/MOTO (không có chip/NFC)", "MANUAL_ENTRY" if amt >= g.get("manual_entry_kya_above_vnd", 2_000_000) else None, "CARD_MANUAL_ENTRY"))
    if a.get("chip_fallback") or (em == "MAGSTRIPE" and a.get("card_product") != "PREPAID"):
        S.append((0.25, "Quẹt từ/fallback dù thẻ có chip (dấu hiệu thẻ giả/skimming)", "CHIP_FALLBACK", "CARD_SKIMMING"))
    if em == "CONTACTLESS" and amt > g.get("contactless_no_cvm_above_vnd", 1_000_000) and auth in (None, "NONE"):
        S.append((0.20, "Giao dịch chạm vượt hạn mức không cần xác thực", "CONTACTLESS_NO_CVM", "CARD_SKIMMING"))
    if st in ("CASH_ADVANCE", "QUASI_CASH") and a.get("kind") != "ATM_WITHDRAWAL":
        S.append((0.25, f"Giao dịch {SUBTYPES[st].lower()} (rút tiền mặt/quasi-cash)", None, "QUASI_CASH_CRYPTO"))
    if st == "REFUND":
        if not a.get("refund_original_ref"):
            S.append((0.30, "Hoàn tiền không có mã giao dịch gốc", "REFUND_UNMATCHED", "REFUND_ABUSE"))
        if a.get("refund_to_other_card"):
            S.append((0.40, "Hoàn tiền về thẻ khác thẻ đã thanh toán", "REFUND_OTHER_CARD", "REFUND_ABUSE"))
    if st == "CAPTURE" and a.get("preauth_amount") and amt > 1.2 * a["preauth_amount"]:
        S.append((0.30, f"Số tiền capture vượt 120% pre-auth ({a['preauth_amount']:,.0f})", "CAPTURE_OVER_PREAUTH", "CARD_MERCHANT_ABUSE"))
    if st == "RECURRING" and new_merchant:
        S.append((0.15, "Thanh toán định kỳ lần đầu tại merchant mới", None, None))
    if net == "NAPAS" and a.get("country") and a["country"] != "VN":
        S.append((0.40, "Thẻ nội địa NAPAS dùng ở nước ngoài", "DOMESTIC_CARD_ABROAD", "CARD_SKIMMING"))
    if a.get("card_product") == "VIRTUAL" and a.get("country") not in (None, "VN"):
        S.append((0.10, "Thẻ ảo dùng giao dịch quốc tế", None, None))
    if a.get("qr_type") == "STATIC" and amt >= g.get("static_qr_kya_above_vnd", 5_000_000):
        S.append((0.20, "QR tĩnh với số tiền lớn (rủi ro bị thay mã QR)", "STATIC_QR_HIGH", "QR_SWAP"))
    if a.get("kind") == "CARD_STATEMENT_PAYMENT":
        sb = a.get("statement_balance")
        if sb and amt > g.get("statement_overpay_ratio", 1.2) * sb:
            S.append((0.30, f"Trả {amt:,.0f} VND > {g.get('statement_overpay_ratio', 1.2) * 100:.0f}% dư nợ sao kê ({sb:,.0f}) – nghi trả thừa rồi rút/hoàn", "STATEMENT_OVERPAY", "STATEMENT_ABUSE"))
        if a.get("payer_is_cardholder") is False and amt >= g.get("third_party_payer_above_vnd", 5_000_000):
            S.append((0.20, "Người trả nợ không phải chủ thẻ, số tiền lớn", "THIRD_PARTY_PAYER", "THIRD_PARTY_PAYMENT"))
        if a.get("funding_source_type") == "CREDIT_CARD":
            S.append((0.35, "Dùng thẻ tín dụng để trả nợ thẻ tín dụng (biến hạn mức tín dụng thành tiền)", "CC_FUNDS_CC", "CARD_TO_CARD_CASHOUT"))
    if a.get("card_product") == "PREPAID" and st == "TOP_UP" and amt >= g.get("prepaid_topup_high_vnd", 10_000_000):
        S.append((0.20, f"Nạp thẻ trả trước {amt:,.0f} VND", "PREPAID_LOAD_HIGH", "PREPAID_ABUSE"))
    # Di chuyển bất khả thi: giao dịch gần nhất ở quốc gia khác trong < 2 giờ
    last = next((h for h in hist if h.get("country") and h.get("ts")), None)
    if last and a.get("country") and last["country"] != a["country"] and 0 <= a["ts"] - last["ts"] < 2 * 3600 and a.get("kind") != "TRANSFER":
        S.append((0.40, f"Di chuyển bất khả thi: {last['country']} → {a['country']} trong {max(a['ts'] - last['ts'], 0) / 60:.0f} phút", "IMPOSSIBLE_TRAVEL", "IMPOSSIBLE_TRAVEL"))
    return S


def markdown() -> str:
    L = ["# Danh mục thẻ & thanh toán (Card Taxonomy)\n", "Sinh tự động từ `agentmon/cardmodel.py`.\n"]
    for title, tab in (("Mạng thẻ (`card_network`)", NETWORKS), ("Sản phẩm thẻ (`card_product`)", PRODUCTS), ("Loại giao dịch (`txn_subtype`)", SUBTYPES),
                       ("Phương thức nhập thẻ (`entry_mode`)", ENTRY_MODES), ("Xác thực chủ thẻ (`auth_method`)", AUTH_METHODS),
                       ("Loại mã QR (`qr_scheme`)", QR_SCHEMES), ("QR tĩnh/động (`qr_type`)", QR_TYPES)):
        L += [f"## {title}\n", "| Mã | Ý nghĩa |", "|---|---|"] + [f"| `{k}` | {v} |" for k, v in tab.items()] + [""]
    return "\n".join(L)
