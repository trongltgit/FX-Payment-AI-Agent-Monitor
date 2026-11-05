"""
HQ Pricing Policy (Cấp 1 – Hội sở chính / TSC)
==============================================

- Chỉ role HQ được xem / sửa.
- CN và Khách hàng KHÔNG bao giờ nhận được dữ liệu này qua API.
- CN vẫn được xem market price (giá thị trường công khai).

Thành phần:
  * base_spread   : điểm spread HQ theo tier/currency/side
  * max_branch_margin : trần margin CN được phép cộng
  * tgdh_points   : điểm điều hòa (TGDH / NSDH) – cộng/trừ vào final price
"""

from copy import deepcopy
from decimal import Decimal
from threading import Lock
from typing import Any, Dict

class HQPolicyError(Exception):
    pass


_lock = Lock()

HQ_BASE_SPREAD: Dict[str, Dict[str, Dict[str, str]]] = {
    "GOLD": {
        "USD": {"BUY": "12", "SELL": "15"},
        "EUR": {"BUY": "22", "SELL": "26"},
        "GBP": {"BUY": "30", "SELL": "35"},
        "JPY": {"BUY": "0.15", "SELL": "0.20"},
        "AUD": {"BUY": "18", "SELL": "22"},
        "SGD": {"BUY": "16", "SELL": "20"},
    },
    "SILVER": {
        "USD": {"BUY": "22", "SELL": "26"},
        "EUR": {"BUY": "35", "SELL": "40"},
        "GBP": {"BUY": "45", "SELL": "50"},
        "JPY": {"BUY": "0.30", "SELL": "0.35"},
        "AUD": {"BUY": "28", "SELL": "32"},
        "SGD": {"BUY": "25", "SELL": "30"},
    },
    "BRONZE": {
        "USD": {"BUY": "32", "SELL": "38"},
        "EUR": {"BUY": "50", "SELL": "55"},
        "GBP": {"BUY": "60", "SELL": "65"},
        "JPY": {"BUY": "0.40", "SELL": "0.50"},
        "AUD": {"BUY": "38", "SELL": "42"},
        "SGD": {"BUY": "35", "SELL": "40"},
    },
}

HQ_MAX_BRANCH_MARGIN: Dict[str, Dict[str, str]] = {
    "GOLD": {
        "USD": "20", "EUR": "25", "GBP": "30",
        "JPY": "0.30", "AUD": "25", "SGD": "22",
    },
    "SILVER": {
        "USD": "30", "EUR": "35", "GBP": "40",
        "JPY": "0.40", "AUD": "35", "SGD": "32",
    },
    "BRONZE": {
        "USD": "40", "EUR": "45", "GBP": "50",
        "JPY": "0.50", "AUD": "45", "SGD": "42",
    },
}

# TGDH / NSDH: điểm điều hòa cộng (+) hoặc trừ (-) vào final price
# Key: currency → points (có thể âm)
HQ_TGDH_POINTS: Dict[str, str] = {
    "USD": "0",
    "EUR": "0",
    "GBP": "0",
    "JPY": "0",
    "AUD": "0",
    "SGD": "0",
}


class HQPolicyService:

    def get_all_policies(self) -> Dict[str, Any]:
        """Chỉ gọi từ API role HQ."""
        with _lock:
            return {
                "base_spread": deepcopy(HQ_BASE_SPREAD),
                "max_branch_margin": deepcopy(HQ_MAX_BRANCH_MARGIN),
                "tgdh_points": deepcopy(HQ_TGDH_POINTS),
            }

    def update_base_spread(
        self,
        tier: str,
        currency: str,
        side: str,
        value: Any,
    ) -> None:
        tier = tier.upper().strip()
        currency = currency.upper().strip()
        side = side.upper().strip()
        if tier not in HQ_BASE_SPREAD:
            raise HQPolicyError(f"Tier {tier} không tồn tại.")
        if currency not in HQ_BASE_SPREAD[tier]:
            raise HQPolicyError(f"Currency {currency} không có trong tier {tier}.")
        if side not in ("BUY", "SELL"):
            raise HQPolicyError("Side phải là BUY hoặc SELL.")
        try:
            d = Decimal(str(value))
            if d < 0:
                raise HQPolicyError("base_spread không được âm.")
        except Exception as exc:
            raise HQPolicyError("Giá trị base_spread không hợp lệ.") from exc

        with _lock:
            HQ_BASE_SPREAD[tier][currency][side] = str(d)

    def update_max_branch_margin(
        self,
        tier: str,
        currency: str,
        value: Any,
    ) -> None:
        tier = tier.upper().strip()
        currency = currency.upper().strip()
        if tier not in HQ_MAX_BRANCH_MARGIN:
            raise HQPolicyError(f"Tier {tier} không tồn tại.")
        if currency not in HQ_MAX_BRANCH_MARGIN[tier]:
            raise HQPolicyError(f"Currency {currency} không có trong tier {tier}.")
        try:
            d = Decimal(str(value))
            if d < 0:
                raise HQPolicyError("max_branch_margin không được âm.")
        except Exception as exc:
            raise HQPolicyError("Giá trị max_branch_margin không hợp lệ.") from exc

        with _lock:
            HQ_MAX_BRANCH_MARGIN[tier][currency] = str(d)

    def update_tgdh_points(self, currency: str, value: Any) -> None:
        """
        Cập nhật điểm điều hòa TGDH (NSDH).
        value có thể dương (cộng) hoặc âm (trừ) vào final price.
        """
        currency = currency.upper().strip()
        if currency not in HQ_TGDH_POINTS:
            raise HQPolicyError(f"Currency {currency} không hỗ trợ TGDH.")
        try:
            d = Decimal(str(value))
        except Exception as exc:
            raise HQPolicyError("Giá trị tgdh_points không hợp lệ.") from exc

        with _lock:
            HQ_TGDH_POINTS[currency] = str(d)

    def get_base_spread(self, pricing_tier: str, currency: str, side: str) -> Decimal:
        tier = (pricing_tier or "").upper().strip()
        currency = currency.upper().strip()
        side = side.upper().strip()
        with _lock:
            tier_cfg = HQ_BASE_SPREAD.get(tier)
            if not tier_cfg:
                raise HQPolicyError(f"Không có chính sách HQ cho tier {tier}.")
            cur_cfg = tier_cfg.get(currency)
            if not cur_cfg:
                raise HQPolicyError(f"Không có chính sách HQ cho {tier}/{currency}.")
            value = cur_cfg.get(side)
            if value is None:
                raise HQPolicyError(f"Không có chính sách HQ cho {tier}/{currency}/{side}.")
            return Decimal(str(value))

    def get_max_branch_margin(self, pricing_tier: str, currency: str) -> Decimal:
        tier = (pricing_tier or "").upper().strip()
        currency = currency.upper().strip()
        with _lock:
            tier_cfg = HQ_MAX_BRANCH_MARGIN.get(tier)
            if not tier_cfg:
                raise HQPolicyError(f"Không có trần margin cho tier {tier}.")
            value = tier_cfg.get(currency)
            if value is None:
                raise HQPolicyError(f"Không có trần margin cho {tier}/{currency}.")
            return Decimal(str(value))

    def get_tgdh_points(self, currency: str) -> Decimal:
        currency = currency.upper().strip()
        with _lock:
            value = HQ_TGDH_POINTS.get(currency, "0")
            return Decimal(str(value))

    def validate_branch_margin(
        self, pricing_tier: str, currency: str, branch_margin: Any
    ) -> Decimal:
        try:
            margin = Decimal(str(branch_margin))
        except Exception as exc:
            raise HQPolicyError("branch_margin không hợp lệ.") from exc
        if margin < 0:
            raise HQPolicyError("branch_margin không được âm.")
        max_allowed = self.get_max_branch_margin(pricing_tier, currency)
        if margin > max_allowed:
            raise HQPolicyError("branch_margin vượt trần cho phép của chi nhánh.")
        return margin


hq_policy_service = HQPolicyService()
