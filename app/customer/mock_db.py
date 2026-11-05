"""
Mock Customer DB + Users
Roles: HQ (TSC) | CN_ADMIN | PNV (staff) | CUSTOMER
Demo: 10 KH, 2 CN, TSC quản toàn bộ user.
"""
import os
import secrets
import time
from copy import deepcopy
from threading import Lock

from werkzeug.security import check_password_hash, generate_password_hash

from utils import store

_lock = Lock()

DEMO_CUSTOMERS = {
    f"CUST{str(i).zfill(3)}": {
        "customer_id": f"CUST{str(i).zfill(3)}",
        "cif": f"000{1000000 + i}",
        "customer_name": [
            "Nguyen Van A", "Cong ty ABC", "Tran Thi B", "Le Van C", "Pham Thi D",
            "Hoang Van E", "Vu Thi F", "Do Van G", "Bui Thi H", "Ngo Van I",
        ][i - 1],
        "segment": ["VIP", "CORPORATE", "STANDARD", "STANDARD", "VIP",
                    "CORPORATE", "STANDARD", "VIP", "STANDARD", "CORPORATE"][i - 1],
        "status": "ACTIVE" if i < 10 else "INACTIVE",
        "pricing_tier": ["GOLD", "SILVER", "BRONZE", "BRONZE", "GOLD",
                         "SILVER", "BRONZE", "GOLD", "SILVER", "BRONZE"][i - 1],
        "online": i <= 5,
        "daily_limit": [5000000, 2000000, 500000, 500000, 3000000,
                        1500000, 400000, 4000000, 800000, 1000000][i - 1],
        "monthly_limit": [50000000, 20000000, 5000000, 5000000, 30000000,
                          15000000, 4000000, 40000000, 8000000, 10000000][i - 1],
        "currency_permissions": (
            ["USD", "EUR", "GBP", "JPY", "AUD", "SGD"] if i <= 3
            else ["USD", "EUR", "SGD"] if i <= 7
            else ["USD", "EUR"]
        ),
        "branch_id": "CN001" if i in (1, 3, 4, 5, 8) else "CN002",
    }
    for i in range(1, 11)
}
# fix CUST010 inactive
DEMO_CUSTOMERS["CUST010"]["status"] = "INACTIVE"
DEMO_CUSTOMERS["CUST010"]["online"] = False

DEMO_BRANCHES = {
    "CN001": {
        "branch_id": "CN001",
        "branch_name": "Chi nhanh Quan 1",
        "customer_ids": ["CUST001", "CUST003", "CUST004", "CUST005", "CUST008"],
    },
    "CN002": {
        "branch_id": "CN002",
        "branch_name": "Chi nhanh Quan 3",
        "customer_ids": ["CUST002", "CUST006", "CUST007", "CUST009", "CUST010"],
    },
}

DEMO_USERS = {
    "hq01": {
        "user_id": "hq01", "password": "demo123", "role": "HQ",
        "name": "Quan tri TSC",
        "permitted_customers": [f"CUST{str(i).zfill(3)}" for i in range(1, 11)],
        "branch_ids": ["CN001", "CN002"],
    },
    "admin_cn01": {
        "user_id": "admin_cn01", "password": "demo123", "role": "CN_ADMIN",
        "name": "Admin CN Quan 1", "branch_id": "CN001",
        "permitted_customers": ["CUST001", "CUST003", "CUST004", "CUST005", "CUST008"],
    },
    "admin_cn02": {
        "user_id": "admin_cn02", "password": "demo123", "role": "CN_ADMIN",
        "name": "Admin CN Quan 3", "branch_id": "CN002",
        "permitted_customers": ["CUST002", "CUST006", "CUST007", "CUST009", "CUST010"],
    },
    "staff01": {
        "user_id": "staff01", "password": "demo123", "role": "PNV",
        "name": "NV CN1 - A", "branch_id": "CN001",
        "permitted_customers": ["CUST001", "CUST003"],
    },
    "staff02": {
        "user_id": "staff02", "password": "demo123", "role": "PNV",
        "name": "NV CN1 - B", "branch_id": "CN001",
        "permitted_customers": ["CUST004", "CUST005", "CUST008"],
    },
    "staff03": {
        "user_id": "staff03", "password": "demo123", "role": "PNV",
        "name": "NV CN2 - A", "branch_id": "CN002",
        "permitted_customers": ["CUST002", "CUST006"],
    },
    "cust001": {
        "user_id": "cust001", "password": "demo123", "role": "CUSTOMER",
        "name": "Nguyen Van A", "customer_id": "CUST001",
        "permitted_customers": ["CUST001"],
    },
    "cust002": {
        "user_id": "cust002", "password": "demo123", "role": "CUSTOMER",
        "name": "Cong ty ABC", "customer_id": "CUST002",
        "permitted_customers": ["CUST002"],
    },
    "cust003": {
        "user_id": "cust003", "password": "demo123", "role": "CUSTOMER",
        "name": "Tran Thi B", "customer_id": "CUST003",
        "permitted_customers": ["CUST003"],
    },
    "cust004": {
        "user_id": "cust004", "password": "demo123", "role": "CUSTOMER",
        "name": "Le Van C", "customer_id": "CUST004",
        "permitted_customers": ["CUST004"],
    },
    "cust005": {
        "user_id": "cust005", "password": "demo123", "role": "CUSTOMER",
        "name": "Pham Thi D", "customer_id": "CUST005",
        "permitted_customers": ["CUST005"],
    },
}

# --- Mật khẩu: KHÔNG lưu chữ thường. Demo dùng chung 1 mật khẩu lấy từ env DEMO_PASSWORD.
# Production thật phải thay toàn bộ khối này bằng thư mục người dùng (DB / LDAP / SSO).
_DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "demo123")
_PW_HASH = generate_password_hash(_DEMO_PASSWORD)
_DUMMY_HASH = generate_password_hash(secrets.token_hex(12))   # so khớp giả cho user không tồn tại
for _u in DEMO_USERS.values():
    _u.pop("password", None)
    _u["password_hash"] = _PW_HASH
    _totp = os.environ.get("TOTP_SECRET_" + _u["user_id"].upper(), "").strip()
    if _totp:
        _u["totp_secret"] = _totp

_SECRET_FIELDS = {"password", "password_hash", "totp_secret"}


def get_demo_customer(customer_id: str):
    data = DEMO_CUSTOMERS.get(customer_id)
    return deepcopy(data) if data else None


def get_demo_customer_by_cif(cif: str):
    cif = str(cif or "").strip()
    for c in DEMO_CUSTOMERS.values():
        if str(c.get("cif", "")).strip() == cif:
            return deepcopy(c)
    return None


def list_demo_customers():
    return [deepcopy(c) for c in DEMO_CUSTOMERS.values()]


def list_demo_customers_by_ids(ids):
    return [deepcopy(DEMO_CUSTOMERS[i]) for i in (ids or []) if i in DEMO_CUSTOMERS]


def list_active_customers():
    return [deepcopy(c) for c in DEMO_CUSTOMERS.values() if c["status"] == "ACTIVE"]


def get_demo_user(username: str):
    user = DEMO_USERS.get(username)
    return deepcopy(user) if user else None


def list_demo_users():
    return [deepcopy({k: v for k, v in u.items() if k not in _SECRET_FIELDS}) for u in DEMO_USERS.values()]


def list_demo_branches():
    return [deepcopy(b) for b in DEMO_BRANCHES.values()]


def get_demo_branch(branch_id: str):
    b = DEMO_BRANCHES.get(branch_id)
    return deepcopy(b) if b else None


def customers_of_branch(branch_id: str):
    b = DEMO_BRANCHES.get(branch_id)
    if not b:
        return []
    return list_demo_customers_by_ids(b.get("customer_ids") or [])


def authenticate_demo_user(username: str, password: str):
    """Xác thực mật khẩu (băm scrypt, so sánh thời gian không đổi).
    Với user không tồn tại vẫn băm 1 lần để không lộ 'user có tồn tại hay không' qua thời gian phản hồi."""
    user = DEMO_USERS.get(username)
    ok = check_password_hash(user["password_hash"] if user else _DUMMY_HASH, password or "")
    if not user or not ok:
        return None
    return deepcopy(user)


def is_user_blocked(user_id: str):
    return store.exists(f"blocked:{user_id}")


def block_user(user_id: str, reason: str, blocked_by: str = "system"):
    """Khóa user VÀ thu hồi ngay mọi phiên đang mở (cookie cũ vô hiệu)."""
    info = {
        "user_id": user_id,
        "reason": reason,
        "blocked_at": int(time.time()),
        "blocked_by": blocked_by,
    }
    store.set_json(f"blocked:{user_id}", info)          # không hết hạn -> TSC phải mở khóa
    try:
        from utils.server_session import revoke_user
        revoke_user(user_id)
    except Exception:
        pass
    return deepcopy(info)


def unlock_user(user_id: str):
    store.delete(f"risk:chal:{user_id}")
    return store.delete(f"blocked:{user_id}")


def list_blocked_users():
    out = []
    for k in store.keys("blocked:"):
        rec = store.get_json(k)
        if rec:
            out.append(rec)
    return out


def assign_cif_to_staff(admin_user_id: str, staff_user_id: str, customer_ids: list):
    admin = DEMO_USERS.get(admin_user_id)
    staff = DEMO_USERS.get(staff_user_id)
    if not admin or admin.get("role") != "CN_ADMIN":
        return False, "Chỉ Admin CN được gán CIF."
    if not staff or staff.get("role") not in {"PNV", "STAFF"}:
        return False, "User không phải nhân viên CN."
    if admin.get("branch_id") != staff.get("branch_id"):
        return False, "Khác chi nhánh."
    branch = DEMO_BRANCHES.get(admin.get("branch_id") or "")
    allowed = set((branch or {}).get("customer_ids") or [])
    for cid in customer_ids:
        if cid not in allowed:
            return False, f"CIF {cid} không thuộc chi nhánh."
    staff["permitted_customers"] = list(customer_ids)
    return True, "OK"


def set_customer_online(customer_id: str, online: bool, actor_role: str, branch_id: str = ""):
    c = DEMO_CUSTOMERS.get(customer_id)
    if not c:
        return False, "Không tìm thấy CIF."
    if actor_role not in {"CN_ADMIN", "PNV", "STAFF", "HQ"}:
        return False, "Không có quyền."
    if actor_role != "HQ" and branch_id:
        branch = DEMO_BRANCHES.get(branch_id)
        if not branch or customer_id not in branch.get("customer_ids", []):
            return False, "CIF không thuộc chi nhánh."
    c["online"] = bool(online)
    return True, "OK"


def tsc_upsert_user(actor_role: str, payload: dict):
    """TSC tạo/sửa user demo."""
    if actor_role != "HQ":
        return False, "Chỉ TSC được quản lý user."
    uid = str(payload.get("user_id") or "").strip()
    if not uid:
        return False, "Thiếu user_id."
    role = str(payload.get("role") or "").upper()
    if role not in {"HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER"}:
        return False, "Role không hợp lệ."
    new_pw = str(payload.get("password") or "")
    existing = DEMO_USERS.get(uid, {})
    if not existing and len(new_pw) < 12:
        return False, "User mới cần password >= 12 ký tự."
    if new_pw and len(new_pw) < 12:
        return False, "Password phải >= 12 ký tự."
    with _lock:
        DEMO_USERS[uid] = {
            "user_id": uid,
            "password_hash": generate_password_hash(new_pw) if new_pw else existing.get("password_hash"),
            "totp_secret": existing.get("totp_secret"),
            "role": role,
            "name": payload.get("name") or existing.get("name") or uid,
            "branch_id": payload.get("branch_id") or existing.get("branch_id"),
            "branch_ids": payload.get("branch_ids") or existing.get("branch_ids") or [],
            "customer_id": payload.get("customer_id") or existing.get("customer_id"),
            "permitted_customers": payload.get("permitted_customers")
            or existing.get("permitted_customers") or [],
        }
    return True, "OK"
