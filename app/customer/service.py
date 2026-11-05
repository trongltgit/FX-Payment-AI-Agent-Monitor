"""
Customer Service
================

Lớp nghiệp vụ: lấy customer, kiểm tra quyền, hạn mức.
Không tin customer_id từ client – luôn lấy từ session + kiểm tra quyền.
"""

from app.customer.mock_db import list_demo_branches, customers_of_branch, get_demo_branch
from app.customer.repository import (
    CustomerAPIRepository,
    CustomerAPIError,
    CustomerAPIUnavailable,
    CustomerAPITimeout,
)

try:
    from app.customer.mock_db import authenticate_demo_user
except ImportError:
    def authenticate_demo_user(username, password):
        return None


class CustomerNotFound(Exception):
    pass


class CustomerInactive(Exception):
    pass


class CustomerAccessDenied(Exception):
    pass


class CustomerService:

    def __init__(self, repository=None):
        self.repository = repository or CustomerAPIRepository()

    def get_customer(self, customer_id):
        customer = self.repository.get_customer(customer_id)
        if not customer:
            raise CustomerNotFound("Không tìm thấy khách hàng.")
        status = str(customer.get("status", "")).upper()
        if status not in {"ACTIVE", "ACTIVATED", "OPEN"}:
            raise CustomerInactive("Khách hàng không ở trạng thái hoạt động.")
        return customer

    def get_customer_by_cif(self, cif):
        customer = self.repository.get_customer_by_cif(cif)
        if not customer:
            raise CustomerNotFound("Không tìm thấy CIF.")
        status = str(customer.get("status", "")).upper()
        if status not in {"ACTIVE", "ACTIVATED", "OPEN"}:
            raise CustomerInactive("Khách hàng không ở trạng thái hoạt động.")
        return customer

    def check_user_access(self, user: dict, customer_id: str) -> bool:
        if not user or not customer_id:
            return False
        permitted = user.get("permitted_customers") or []
        if customer_id in permitted:
            return True
        if user.get("role") == "CUSTOMER" and user.get("customer_id") == customer_id:
            return True
        # HQ được xem các CIF trong permitted
        if (user.get("role") or "").upper() == "HQ" and customer_id in permitted:
            return True
        return False

    def check_currency_permission(self, customer, currency):
        permissions = customer.get("currency_permissions") or []
        if not permissions:
            return True
        normalized = {str(item).upper() for item in permissions}
        return currency.upper() in normalized

    def check_amount_limit(self, customer, amount):
        daily_limit = customer.get("daily_limit")
        if daily_limit is None:
            return True
        try:
            return float(amount) <= float(daily_limit)
        except (TypeError, ValueError):
            return False

    def authenticate(self, username: str, password: str):
        """
        Demo authentication.
        Production: thay bằng LDAP / OAuth / JWT + MFA.
        """
        return authenticate_demo_user(username, password)

    def list_permitted_customers(self, user: dict):
        if not user:
            return []
        permitted_ids = user.get("permitted_customers") or []
        result = []
        for cid in permitted_ids:
            try:
                c = self.get_customer(cid)
                result.append({
                    "customer_id": c["customer_id"],
                    "cif": c.get("cif"),
                    "customer_name": c.get("customer_name"),
                    "segment": c.get("segment"),
                    "pricing_tier": c.get("pricing_tier"),
                    "online": bool(c.get("online", False)),
                })
            except (CustomerNotFound, CustomerInactive):
                continue
        return result


    def list_branches(self, user: dict):
        """HQ xem tất cả CN; PNV chỉ thấy CN của mình."""
        role = (user.get("role") or "").upper()
        all_b = list_demo_branches()
        if role == "HQ":
            return all_b
        bid = user.get("branch_id")
        if bid:
            b = get_demo_branch(bid)
            return [b] if b else []
        return []

    def list_customers_by_branch(self, user: dict, branch_id: str):
        role = (user.get("role") or "").upper()
        if role == "PNV":
            if user.get("branch_id") and user.get("branch_id") != branch_id:
                return []
        customers = customers_of_branch(branch_id)
        permitted = set(user.get("permitted_customers") or [])
        if permitted:
            customers = [c for c in customers if c and c["customer_id"] in permitted]
        return [
            {
                "customer_id": c["customer_id"],
                "cif": c.get("cif"),
                "customer_name": c.get("customer_name"),
                "segment": c.get("segment"),
                "pricing_tier": c.get("pricing_tier"),
                "online": bool(c.get("online", False)),
            }
            for c in customers if c
        ]
