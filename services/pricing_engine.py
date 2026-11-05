"""
Pricing Engine
==============
Base TSC → + HQ spread → + CN margin → final_price
NSDH / TGDH (tùy chọn – chỉ khi CN chọn dùng ngân sách điều hòa):
  - NH bán (SELL): TGDH = final − điểm NSDH
  - NH mua (BUY):  TGDH = final + điểm NSDH

CN chỉ thấy: final_price + margin CN + (tgdh nếu chọn NSDH)
KH chỉ thấy: giá đã điều hòa nếu CN set NSDH, không thì final
TSC thấy hết; margin CN chỉ lộ sau deal done.

Side API = chiều NH:
  BUY  = NH mua  → base − spread (thấp)
  SELL = NH bán  → base + spread (cao)
→ Cùng CIF + cùng lúc: giá KH mua > giá KH bán.
"""

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional
import os
import time
from services.hq_policy import hq_policy_service, HQPolicyError


class PricingError(Exception):
    pass


class PricingEngine:
    SUPPORTED_CURRENCIES = {"USD", "EUR", "GBP", "JPY", "AUD", "SGD"}
    SUPPORTED_SIDES = {"BUY", "SELL"}
    DEFAULT_VALID_SECONDS = 60

    def __init__(self):
        try:
            self.valid_for_seconds = int(
                os.environ.get("PRICING_QUOTE_VALID_SECONDS", str(self.DEFAULT_VALID_SECONDS))
            )
        except (TypeError, ValueError):
            self.valid_for_seconds = self.DEFAULT_VALID_SECONDS
        if self.valid_for_seconds <= 0:
            self.valid_for_seconds = self.DEFAULT_VALID_SECONDS

    def validate_request(self, currency, side, amount) -> Decimal:
        currency = str(currency or "").upper().strip()
        side = str(side or "").upper().strip()
        if currency not in self.SUPPORTED_CURRENCIES:
            raise PricingError("Currency không được hỗ trợ.")
        if side not in self.SUPPORTED_SIDES:
            raise PricingError("Side phải là BUY hoặc SELL.")
        try:
            amount = Decimal(str(amount))
        except Exception as exc:
            raise PricingError("Amount không hợp lệ.") from exc
        if not amount.is_finite() or amount <= 0:
            raise PricingError("Amount phải lớn hơn 0.")
        return amount

    def validate_base_price(self, base_price) -> Decimal:
        try:
            rate = Decimal(str(base_price))
        except Exception as exc:
            raise PricingError("Base price không hợp lệ.") from exc
        if not rate.is_finite() or rate <= 0:
            raise PricingError("Base price phải lớn hơn 0.")
        return rate

    def calculate_price(
        self,
        customer: Dict[str, Any],
        currency: str,
        side: str,
        amount: Any,
        base_price: Any,
        branch_margin: Any = 0,
        viewer_role: str = "CUSTOMER",
        use_nsdh: bool = False,
        nsdh_points: Any = 0,
    ) -> Dict[str, Any]:
        """
        use_nsdh: CN chọn dùng ngân sách điều hòa hay không.
        nsdh_points: số điểm CN set (chỉ áp khi use_nsdh=True).
        """
        currency = str(currency).upper().strip()
        side = str(side).upper().strip()
        role = (viewer_role or "CUSTOMER").upper()
        amount = self.validate_request(currency, side, amount)
        base_price = self.validate_base_price(base_price)

        if not customer.get("customer_id"):
            raise PricingError("Thiếu customer_id.")
        status = str(customer.get("status", "")).upper()
        if status not in {"ACTIVE", "ACTIVATED", "OPEN"}:
            raise PricingError("Customer không hoạt động.")

        pricing_tier = str(
            customer.get("pricing_tier") or customer.get("segment") or "BRONZE"
        ).upper().strip()

        try:
            hq_spread = hq_policy_service.get_base_spread(pricing_tier, currency, side)
        except HQPolicyError as exc:
            raise PricingError(str(exc)) from exc

        try:
            branch_m = hq_policy_service.validate_branch_margin(
                pricing_tier, currency, branch_margin if branch_margin is not None else 0
            )
        except HQPolicyError as exc:
            raise PricingError(str(exc)) from exc

        total_spread = hq_spread + branch_m

        if side == "BUY":
            final_price = base_price - total_spread
        else:
            final_price = base_price + total_spread

        if final_price <= 0:
            raise PricingError("Final price không hợp lệ.")

        # NSDH / TGDH – chỉ khi CN chọn
        use_nsdh = bool(use_nsdh)
        try:
            pts = abs(Decimal(str(nsdh_points or 0)))
        except Exception:
            pts = Decimal("0")

        if use_nsdh and pts > 0:
            if side == "SELL":
                tgdh_price = final_price - pts
            else:
                tgdh_price = final_price + pts
            if tgdh_price <= 0:
                raise PricingError("TGDH price không hợp lệ.")
        else:
            tgdh_price = final_price
            pts = Decimal("0")
            use_nsdh = False

        final_price = final_price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        tgdh_price = tgdh_price.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        issued_at = int(time.time())

        # Giá khách hàng nhận = tgdh nếu có NSDH, không thì final
        customer_price = tgdh_price if use_nsdh else final_price

        if role == "CUSTOMER":
            return {
                "currency": currency,
                "side": side,
                "price": str(customer_price),
                "valid_for_seconds": self.valid_for_seconds,
                "issued_at": issued_at,
            }

        # CN: CHỈ final + margin CN + (tgdh nếu chọn NSDH). KHÔNG base, KHÔNG HQ spread.
        if role in {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}:
            out = {
                "currency": currency,
                "side": side,
                "price": str(final_price),
                "branch_margin": str(branch_m),
                "valid_for_seconds": self.valid_for_seconds,
                "issued_at": issued_at,
            }
            if use_nsdh:
                out["tgdh"] = str(tgdh_price)
                out["nsdh_points"] = str(pts)
                out["use_nsdh"] = True
            # max_branch_margin chỉ để CN biết trần khi set margin – không phải "margin HQ"
            try:
                out["max_cn_margin"] = str(
                    hq_policy_service.get_max_branch_margin(pricing_tier, currency)
                )
            except HQPolicyError:
                pass
            return out

        # HQ / TSC: full; margin CN ẩn lúc quote (_branch_margin internal)
        return {
            "currency": currency,
            "side": side,
            "price": str(final_price),
            "tgdh": str(tgdh_price) if use_nsdh else None,
            "use_nsdh": use_nsdh,
            "nsdh_points": str(pts) if use_nsdh else "0",
            "base_price": str(base_price),
            "hq_base_spread": str(hq_spread),
            "total_spread": str(total_spread),
            "pricing_tier": pricing_tier,
            "valid_for_seconds": self.valid_for_seconds,
            "issued_at": issued_at,
            "_branch_margin": str(branch_m),
            "_max_cn_margin": str(
                hq_policy_service.get_max_branch_margin(pricing_tier, currency)
            ),
        }


pricing_engine = PricingEngine()
