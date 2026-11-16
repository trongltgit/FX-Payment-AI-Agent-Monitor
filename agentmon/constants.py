"""Hằng số dùng chung: loại giao dịch, kênh, phiên bản mã nguồn."""

CODE_VERSION = "2.1.0"

# Giao dịch gắn với THẺ (Agent chỉ gửi token thẻ)
CARD_KINDS = ("ONLINE_PURCHASE", "CARD_PAYMENT", "ATM_WITHDRAWAL", "WALLET_PAYMENT", "BILL_PAYMENT", "QR_PAYMENT", "CARD_STATEMENT_PAYMENT")
PAY_KINDS = ("TRANSFER",) + CARD_KINDS

KIND_LABELS = {
    "FX_TRADE": "Lệnh FX", "TRANSFER": "Chuyển tiền", "ONLINE_PURCHASE": "Mua sắm online (E-commerce)",
    "CARD_PAYMENT": "Thanh toán thẻ tại POS", "ATM_WITHDRAWAL": "Rút tiền ATM", "WALLET_PAYMENT": "Thanh toán qua ví điện tử",
    "BILL_PAYMENT": "Thanh toán hóa đơn (Digibank/Digibiz)", "QR_PAYMENT": "Thanh toán QR (Digibank/Digibiz)",
    "CARD_STATEMENT_PAYMENT": "Thanh toán dư nợ sao kê thẻ tín dụng",
}

# Kênh hợp lệ cho từng loại giao dịch (mặc định là phần tử đầu tiên)
KIND_CHANNELS = {
    "TRANSFER": (None, "DIGIBANK", "DIGIBIZ", "PORTAL", "IPS"),
    "ONLINE_PURCHASE": ("CNP", "DIGIBANK", "DIGIBIZ"),
    "CARD_PAYMENT": ("POS", "CNP"),
    "ATM_WITHDRAWAL": ("ATM",),
    "WALLET_PAYMENT": ("WALLET",),
    "BILL_PAYMENT": ("DIGIBANK", "DIGIBIZ"),
    "QR_PAYMENT": ("DIGIBANK", "DIGIBIZ"),
    "CARD_STATEMENT_PAYMENT": ("DIGIBANK", "DIGIBIZ", "PORTAL"),
}
# Kênh "thẻ không xuất trình" – cần thẻ bật thanh toán online
CNP_LIKE = ("CNP", "DIGIBANK", "DIGIBIZ")
WALLET_PROVIDERS = ("APPLE_PAY", "GOOGLE_PAY", "SAMSUNG_PAY", "OTHER")

# Trần theo loại giao dịch (khóa trong policy)
CAP_KEY = {"TRANSFER": "transfer_per_txn", "CARD_PAYMENT": "card_per_txn", "ONLINE_PURCHASE": "online_per_txn",
           "ATM_WITHDRAWAL": "atm_per_txn", "WALLET_PAYMENT": "card_per_txn",
           "BILL_PAYMENT": "qr_bill_per_txn", "QR_PAYMENT": "qr_bill_per_txn", "CARD_STATEMENT_PAYMENT": "qr_bill_per_txn"}

# ---- Người thực hiện và hệ thống nguồn (v1.2) ----
ACTORS = ("AGENT", "HUMAN")
# Hệ thống nguồn gửi giao dịch của NGƯỜI vào Monitor → loại giao dịch được phép + kênh mặc định
SOURCE_SYSTEMS = {
    "PORTAL":       {"name": "Internet banking / Portal",          "kinds": ("FX_TRADE", "TRANSFER", "CARD_STATEMENT_PAYMENT"), "channel": {"TRANSFER": "PORTAL", "CARD_STATEMENT_PAYMENT": "PORTAL"}},
    "DIGIBANK":     {"name": "Digibank (khách cá nhân)",            "kinds": ("TRANSFER", "BILL_PAYMENT", "QR_PAYMENT", "ONLINE_PURCHASE", "CARD_STATEMENT_PAYMENT"), "channel": "DIGIBANK"},
    "DIGIBIZ":      {"name": "Digibiz (khách doanh nghiệp)",        "kinds": ("TRANSFER", "BILL_PAYMENT", "QR_PAYMENT", "ONLINE_PURCHASE", "CARD_STATEMENT_PAYMENT"), "channel": "DIGIBIZ"},
    "CARD_SWITCH":  {"name": "Switch thẻ (POS/CNP/ví)",             "kinds": ("CARD_PAYMENT", "ONLINE_PURCHASE", "WALLET_PAYMENT"), "channel": None},
    "ATM_SWITCH":   {"name": "Switch ATM",                          "kinds": ("ATM_WITHDRAWAL",), "channel": "ATM"},
    "IPS_TRANSFER": {"name": "Chuyển tiền liên ngân hàng (IPS/247)", "kinds": ("TRANSFER",), "channel": {"TRANSFER": "IPS"}},
}
ONLINE_SOURCES = ("PORTAL", "DIGIBANK", "DIGIBIZ")      # kênh cần CIF bật dịch vụ online
HUMAN_PREFIX = "HUMAN:"                                  # agent_id quy ước cho giao dịch của người
