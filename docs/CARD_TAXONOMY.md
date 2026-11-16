# Danh mục thẻ & thanh toán (Card Taxonomy)

Sinh tự động từ `agentmon/cardmodel.py`.

## Mạng thẻ (`card_network`)

| Mã | Ý nghĩa |
|---|---|
| `VISA` | Visa |
| `MASTERCARD` | Mastercard |
| `JCB` | JCB |
| `UNIONPAY` | UnionPay |
| `AMEX` | American Express |
| `DISCOVER_DINERS` | Discover / Diners Club |
| `NAPAS` | NAPAS (thẻ nội địa) |
| `OTHER` | Mạng khác |

## Sản phẩm thẻ (`card_product`)

| Mã | Ý nghĩa |
|---|---|
| `CREDIT` | Thẻ tín dụng |
| `DEBIT` | Thẻ ghi nợ |
| `PREPAID` | Thẻ trả trước |
| `VIRTUAL` | Thẻ ảo (dùng một lần/nhiều lần) |
| `CORPORATE` | Thẻ doanh nghiệp/thương mại |
| `OTHER` | Khác |

## Loại giao dịch (`txn_subtype`)

| Mã | Ý nghĩa |
|---|---|
| `PURCHASE` | Mua hàng |
| `PREAUTH` | Ủy quyền trước (pre-auth) |
| `CAPTURE` | Hoàn tất ủy quyền (capture/completion) |
| `REFUND` | Hoàn tiền |
| `REVERSAL` | Hủy/đảo giao dịch |
| `CASH_ADVANCE` | Ứng tiền mặt |
| `QUASI_CASH` | Quasi-cash |
| `RECURRING` | Thanh toán định kỳ |
| `MOTO` | Đặt hàng qua thư/điện thoại |
| `INSTALLMENT` | Trả góp |
| `CARD_TO_CARD` | Chuyển tiền thẻ-đến-thẻ |
| `TOP_UP` | Nạp tiền (ví/trả trước) |
| `BALANCE_INQUIRY` | Hỏi số dư |

## Phương thức nhập thẻ (`entry_mode`)

| Mã | Ý nghĩa |
|---|---|
| `CHIP` | Chip EMV (cắm) |
| `CONTACTLESS` | Chạm (NFC/contactless) |
| `MAGSTRIPE` | Quẹt từ |
| `MANUAL_KEY` | Nhập tay số thẻ |
| `ECOM` | Thương mại điện tử |
| `WALLET_TOKEN` | Token ví điện tử (Apple/Google/Samsung Pay) |
| `QR` | Quét mã QR |
| `MOTO` | Qua thư/điện thoại |

## Xác thực chủ thẻ (`auth_method`)

| Mã | Ý nghĩa |
|---|---|
| `PIN` | PIN |
| `THREE_DS` | 3-D Secure |
| `OTP` | OTP |
| `BIOMETRIC` | Sinh trắc |
| `CDCVM` | Xác thực trên thiết bị (ví) |
| `SIGNATURE` | Chữ ký |
| `NONE` | Không xác thực |

## Loại mã QR (`qr_scheme`)

| Mã | Ý nghĩa |
|---|---|
| `VIETQR` | VietQR (NAPAS) |
| `NAPAS_247` | NAPAS 247 |
| `EMVCO_MPM` | EMVCo QR (merchant-presented) |
| `CARD_SCHEME_QR` | QR của tổ chức thẻ |
| `WALLET_QR` | QR ví điện tử |
| `OTHER` | Khác |

## QR tĩnh/động (`qr_type`)

| Mã | Ý nghĩa |
|---|---|
| `STATIC` | QR tĩnh |
| `DYNAMIC` | QR động (theo giao dịch) |

