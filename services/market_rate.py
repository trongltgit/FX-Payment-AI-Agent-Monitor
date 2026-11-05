"""
HQ Base Price (Base TSC)
========================
- Demo / Production: TSC (HQ) chọn mode:
    * auto   : tỷ giá tự động dao động real-time mỗi 20 giây
    * manual : TSC set tay, không tự đổi
- CN / KH chỉ nhận final price (không thấy base).
"""
import os
import time
import random
from decimal import Decimal, ROUND_HALF_UP
from threading import Lock
from typing import Any, Dict, Optional

import requests


class MarketRateError(Exception):
    pass


DEMO_BASE = {
    "USD": Decimal("26200"),
    "EUR": Decimal("30600"),
    "GBP": Decimal("35400"),
    "JPY": Decimal("175"),
    "AUD": Decimal("17400"),
    "SGD": Decimal("19800"),
}

# Chu kỳ auto-update (giây) – theo yêu cầu 20s
AUTO_UPDATE_SECONDS = 20


class MarketRateService:
    def __init__(self):
        self.base_url = os.environ.get("MARKET_RATE_API_URL", "").strip().rstrip("/")
        self.api_key = os.environ.get("MARKET_RATE_API_KEY", "").strip()
        self.timeout = float(os.environ.get("MARKET_RATE_API_TIMEOUT", "5"))
        self.demo_mode = not bool(self.base_url)

        try:
            self.demo_jitter_pct = float(os.environ.get("HQ_BASE_JITTER_PCT", "0.08"))
        except ValueError:
            self.demo_jitter_pct = 0.08

        # Mode: "auto" | "manual" – production TSC set qua API
        env_mode = (os.environ.get("HQ_BASE_MODE") or "auto").strip().lower()
        self._mode = env_mode if env_mode in ("auto", "manual") else "auto"

        self._lock = Lock()
        # Current rates (manual hoặc snapshot auto gần nhất)
        self._rates: Dict[str, Decimal] = {k: v for k, v in DEMO_BASE.items()}
        self._last_auto_seed: Optional[int] = None
        self._updated_at: int = int(time.time())

        # Khởi tạo snapshot auto lần đầu
        if self._mode == "auto":
            self._refresh_auto_if_needed(force=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_mode(self) -> str:
        with self._lock:
            return self._mode

    def set_mode(self, mode: str) -> str:
        mode = (mode or "").strip().lower()
        if mode not in ("auto", "manual"):
            raise MarketRateError("Mode phải là 'auto' hoặc 'manual'.")
        with self._lock:
            self._mode = mode
            if mode == "auto":
                self._refresh_auto_if_needed(force=True)
            self._updated_at = int(time.time())
            return self._mode

    def set_manual_rate(self, currency: str, rate: Any) -> str:
        """HQ set tay base price khi mode = manual."""
        currency = str(currency or "").upper().strip()
        if currency not in DEMO_BASE:
            raise MarketRateError(f"Currency {currency} không hỗ trợ.")
        try:
            d = Decimal(str(rate))
        except Exception as exc:
            raise MarketRateError("Rate không hợp lệ.") from exc
        if not d.is_finite() or d <= 0:
            raise MarketRateError("Rate phải lớn hơn 0.")
        d = d.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        with self._lock:
            self._rates[currency] = d
            self._updated_at = int(time.time())
            # Khi set manual rate → tự chuyển sang manual nếu đang auto
            if self._mode == "auto":
                self._mode = "manual"
            return str(d)

    def get_all_rates(self) -> Dict[str, Any]:
        with self._lock:
            if self._mode == "auto":
                self._refresh_auto_if_needed()
            return {
                "mode": self._mode,
                "updated_at": self._updated_at,
                "auto_interval_seconds": AUTO_UPDATE_SECONDS,
                "rates": {k: str(v) for k, v in self._rates.items()},
            }

    def get_rate(self, currency, side=None):
        """
        Lấy base price TSC.
        side được giữ để tương thích API external; demo dùng chung mid-rate.
        """
        currency = str(currency or "").upper().strip()

        if not self.demo_mode:
            return self._fetch_external(currency, side)

        with self._lock:
            if self._mode == "auto":
                self._refresh_auto_if_needed()
            if currency not in self._rates:
                raise MarketRateError(f"Currency {currency} không hỗ trợ.")
            return float(self._rates[currency])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _refresh_auto_if_needed(self, force: bool = False) -> None:
        """Cập nhật tỷ giá auto mỗi AUTO_UPDATE_SECONDS (20s)."""
        now = int(time.time())
        seed = now // AUTO_UPDATE_SECONDS
        if not force and self._last_auto_seed == seed:
            return
        self._last_auto_seed = seed
        for ccy, base in DEMO_BASE.items():
            random.seed(f"{ccy}-{seed}")
            jitter = Decimal(
                str(1 + random.uniform(-self.demo_jitter_pct, self.demo_jitter_pct) / 100)
            )
            self._rates[ccy] = (base * jitter).quantize(
                Decimal("0.0001"), rounding=ROUND_HALF_UP
            )
        self._updated_at = now

    def _fetch_external(self, currency: str, side) -> float:
        headers = {"Accept": "application/json", "User-Agent": "Anti-Bot-Pro/1.0"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            response = requests.get(
                f"{self.base_url}/rate",
                params={"currency": currency, "side": (side or "BUY")},
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise MarketRateError(f"Không kết nối base price: {exc}") from exc
        if response.status_code >= 400:
            raise MarketRateError(f"Base price HTTP {response.status_code}")
        data = response.json()
        rate = data.get("rate")
        if rate is None:
            raise MarketRateError("Không có rate.")
        return float(rate)


market_rate_service = MarketRateService()
