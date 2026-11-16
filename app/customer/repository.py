"""
Customer Repository / Adapter
=============================

- Demo mode: Mock Customer DB (khi CUSTOMER_API_URL trống)
- Production: gọi Customer API thật
"""

import os
import requests

try:
    from app.customer.mock_db import (
        get_demo_customer,
        get_demo_customer_by_cif,
        list_demo_customers,
    )
    _MOCK_AVAILABLE = True
except ImportError:
    _MOCK_AVAILABLE = False
    get_demo_customer = None
    get_demo_customer_by_cif = None
    list_demo_customers = None


class CustomerAPIError(Exception):
    pass


class CustomerAPITimeout(CustomerAPIError):
    pass


class CustomerAPIUnavailable(CustomerAPIError):
    pass


class CustomerAPIRepository:

    def __init__(self):
        self.base_url = os.environ.get("CUSTOMER_API_URL", "").strip()
        self.api_key = os.environ.get("CUSTOMER_API_KEY", "").strip()
        self.timeout = float(os.environ.get("CUSTOMER_API_TIMEOUT", "5"))

        verify_ssl = os.environ.get("CUSTOMER_API_VERIFY_SSL", "1").strip().lower()
        self.verify_ssl = verify_ssl not in {"0", "false", "no", "off"}

        self.demo_mode = not bool(self.base_url)

        if self.demo_mode and not _MOCK_AVAILABLE:
            raise CustomerAPIUnavailable(
                "CUSTOMER_API_URL chưa cấu hình và file mock_db.py không tồn tại. "
                "Hãy đảm bảo app/customer/mock_db.py có trong repo."
            )

        if not self.demo_mode:
            self.base_url = self.base_url.rstrip("/")

    def _headers(self):
        headers = {
            "Accept": "application/json",
            "User-Agent": "Anti-Bot-Pro/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method, path, **kwargs):
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = kwargs.pop("headers", {})
        final_headers = self._headers()
        final_headers.update(headers)

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=final_headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
                **kwargs,
            )
        except requests.Timeout as exc:
            raise CustomerAPITimeout("Customer API timeout.") from exc
        except requests.RequestException as exc:
            raise CustomerAPIUnavailable(
                f"Không thể kết nối Customer API: {exc}"
            ) from exc

        if response.status_code == 404:
            return None
        if response.status_code in (401, 403):
            raise CustomerAPIError("Customer API từ chối quyền truy cập.")
        if response.status_code >= 500:
            raise CustomerAPIUnavailable(
                f"Customer API trả HTTP {response.status_code}."
            )
        if response.status_code >= 400:
            raise CustomerAPIError(
                f"Customer API trả HTTP {response.status_code}."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise CustomerAPIError(
                "Customer API không trả JSON hợp lệ."
            ) from exc

    def get_customer(self, customer_id):
        if self.demo_mode:
            return get_demo_customer(customer_id)
        if not customer_id:
            return None
        data = self._request("GET", f"/customers/{customer_id}")
        return self._normalize_customer(data)

    def get_customer_by_cif(self, cif):
        if self.demo_mode:
            return get_demo_customer_by_cif(cif)
        if not cif:
            return None
        data = self._request("GET", f"/customers/by-cif/{cif}")
        return self._normalize_customer(data)

    def list_customers(self):
        if self.demo_mode:
            return list_demo_customers()
        data = self._request("GET", "/customers")
        if isinstance(data, list):
            return [self._normalize_customer(c) for c in data if c]
        if isinstance(data, dict) and isinstance(data.get("data"), list):
            return [self._normalize_customer(c) for c in data["data"] if c]
        return []

    def _normalize_customer(self, data):
        if not data:
            return None
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        return {
            "customer_id": data.get("customer_id") or data.get("id"),
            "cif": data.get("cif"),
            "customer_name": data.get("customer_name") or data.get("name"),
            "segment": data.get("segment"),
            "status": str(data.get("status", "")).upper(),
            "pricing_tier": data.get("pricing_tier") or data.get("pricingTier"),
            "daily_limit": data.get("daily_limit"),
            "monthly_limit": data.get("monthly_limit"),
            "currency_permissions": data.get("currency_permissions", []),
            "pricing": data.get("pricing") or {},
            "raw": data,
        }
