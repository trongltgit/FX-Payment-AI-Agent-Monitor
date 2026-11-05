"""
Đăng ký AI Agent với ngân hàng (cơ sở pháp lý):
  KH đăng ký (đồng ý điều khoản + có Authenticator) → CN_ADMIN duyệt & đặt hạn mức ≤ trần TSC → ACTIVE → KH tự cấp API key.
Agent không có hồ sơ ACTIVE còn hiệu lực KHÔNG được giao dịch (hard block).
"""
import hashlib
import hmac
import re
import secrets
import time

from agentmon import db, policy
from utils import store

CONSENT_VERSION = "2026-01"
CONSENT_TEXT = (
    "1. Tôi/Doanh nghiệp tôi ủy quyền cho phần mềm AI Agent được liệt kê thực hiện các loại giao dịch đã đăng ký, trong hạn mức do Ngân hàng phê duyệt.\n"
    "2. Tôi chịu trách nhiệm pháp lý đối với mọi giao dịch phát sinh từ AI Agent này, kể cả khi Agent hoạt động tự động.\n"
    "3. Tôi đồng ý để Ngân hàng giám sát hành vi giao dịch, phân tích bằng mô hình học máy và hệ thống AI, và có quyền xác minh, tạm giữ, từ chối hoặc đình chỉ Agent khi phát hiện bất thường.\n"
    "4. Giao dịch bất thường sẽ được gửi tới ứng dụng Authenticator của tôi để xác minh (KYA); tôi cam kết bảo mật thiết bị, PIN và API key.\n"
    "5. Tôi không cung cấp số thẻ đầy đủ, CVV/CVC hoặc PIN cho Agent; Agent chỉ dùng token thẻ do Ngân hàng cấp.\n"
    "6. Ngân hàng có quyền thay đổi/thu hồi hạn mức và hiệu lực đăng ký bất kỳ lúc nào theo quy định.")


def consent_hash():
    return hashlib.sha256((CONSENT_VERSION + CONSENT_TEXT).encode()).hexdigest()


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def get(agent_id):
    r = db.one("SELECT * FROM agents WHERE agent_id=?", (agent_id,))
    return _dec(r)


def _dec(r):
    if not r:
        return None
    r["domains"] = db.jload(r.get("domains"), [])
    r["kinds"] = db.jload(r.get("kinds"), [])
    r["limits"] = db.jload(r.get("limits"), {})
    r["requested_limits"] = db.jload(r.get("requested_limits"), {})
    return r


def list_agents(customer_ids=None, status=None):
    sql, args, w = "SELECT * FROM agents", [], []
    if customer_ids is not None:
        if not customer_ids:
            return []
        w.append("customer_id IN (%s)" % ",".join("?" * len(customer_ids)))
        args += list(customer_ids)
    if status:
        w.append("status=?")
        args.append(status)
    if w:
        sql += " WHERE " + " AND ".join(w)
    rows = db.query(sql + " ORDER BY requested_at DESC", args)
    return [public(_dec(r)) for r in rows]


def public(a):
    if not a:
        return None
    d = {k: a[k] for k in ("agent_id", "customer_id", "branch_id", "name", "purpose", "domains", "kinds", "status",
                           "limits", "requested_limits", "consent_version", "consent_at", "requested_at", "approved_by",
                           "approved_at", "valid_until", "reject_reason", "probation_left", "denied_count", "status_note",
                           "key_prefix", "is_demo")}
    d["has_key"] = bool(a.get("key_hash"))
    return d


def register(customer: dict, name, purpose, domains, kinds, requested_limits, ip, agent_id=None):
    name = (name or "").strip()[:60]
    if len(name) < 3:
        return False, "Tên Agent tối thiểu 3 ký tự.", None
    domains = [d for d in (domains or []) if d in ("FX", "PAY")]
    if not domains:
        return False, "Chọn ít nhất một loại hoạt động: FX hoặc Thanh toán.", None
    allowed_kinds = {"FX": ["FX_TRADE"], "PAY": ["TRANSFER", "ONLINE_PURCHASE", "CARD_PAYMENT"]}
    ks = []
    for d in domains:
        ks += [k for k in (kinds or allowed_kinds[d]) if k in allowed_kinds[d]] or allowed_kinds[d]
    aid = agent_id or ("agent-" + re.sub(r"[^a-z0-9]", "", customer["customer_id"].lower()) + "-" + secrets.token_hex(2))
    if get(aid):
        return False, "Agent ID đã tồn tại.", None
    clean_req = {}
    for d in domains:
        clean_req[d] = {k: v for k, v in ((requested_limits or {}).get(d) or {}).items()
                        if k in policy.NUM_KEYS[d] or k in ("allowed_pairs", "hours_from", "hours_to")}
    db.execute("INSERT INTO agents(agent_id,customer_id,branch_id,name,purpose,domains,kinds,status,limits,requested_limits,"
               "consent_version,consent_at,consent_ip,consent_hash,requested_at,probation_left,created_at) "
               "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (aid, customer["customer_id"], customer.get("branch_id"), name, (purpose or "")[:300], db.jdump(domains),
                db.jdump(ks), "PENDING", db.jdump({}), db.jdump(clean_req), CONSENT_VERSION, time.time(), ip,
                consent_hash(), time.time(), 3, time.time()))
    return True, "OK", aid


def approve(agent_id, approver, limits_by_domain: dict, valid_days=365):
    a = get(agent_id)
    if not a or a["status"] != "PENDING":
        return False, "Chỉ duyệt hồ sơ đang chờ."
    from app.customer.mock_db import get_demo_customer
    cust = get_demo_customer(a["customer_id"]) or {}
    seg = cust.get("segment", "STANDARD")
    final = {}
    for d in a["domains"]:
        req = (limits_by_domain or {}).get(d) or (a["requested_limits"] or {}).get(d) or {}
        final[d] = policy.clip_agent_limits(d, seg, a["customer_id"], req)
    db.execute("UPDATE agents SET status='ACTIVE', limits=?, approved_by=?, approved_at=?, valid_until=?, reject_reason=NULL "
               "WHERE agent_id=?", (db.jdump(final), approver, time.time(), time.time() + valid_days * 86400, agent_id))
    return True, "OK"


def reject(agent_id, approver, reason):
    a = get(agent_id)
    if not a or a["status"] != "PENDING":
        return False, "Chỉ từ chối hồ sơ đang chờ."
    db.execute("UPDATE agents SET status='REJECTED', reject_reason=?, approved_by=?, approved_at=? WHERE agent_id=?",
               ((reason or "")[:200], approver, time.time(), agent_id))
    return True, "OK"


def set_status(agent_id, status, note="", by=""):
    if status not in ("ACTIVE", "PAUSED", "SUSPENDED", "REVOKED"):
        return False, "Trạng thái không hợp lệ."
    a = get(agent_id)
    if not a:
        return False, "Không tìm thấy Agent."
    if a["status"] in ("PENDING", "REJECTED"):
        return False, "Hồ sơ chưa được duyệt."
    if a["status"] == "REVOKED":
        return False, "Agent đã bị thu hồi vĩnh viễn."
    db.execute("UPDATE agents SET status=?, status_note=? WHERE agent_id=?", (status, f"{note} [{by}]"[:200], agent_id))
    return True, "OK"


def lower_limits(agent_id, domain, values: dict):
    """KH chỉ được HẠ hạn mức của chính Agent (nâng phải qua CN)."""
    a = get(agent_id)
    if not a or domain not in a["domains"]:
        return False, "Không hợp lệ."
    cur = a["limits"].get(domain, {})
    from app.customer.mock_db import get_demo_customer
    seg = (get_demo_customer(a["customer_id"]) or {}).get("segment", "STANDARD")
    eff = policy.effective_limits(domain, seg, a["customer_id"], cur)
    new = dict(cur)
    for k, v in values.items():
        if k in policy.NUM_KEYS[domain]:
            try:
                v = float(v)
            except (TypeError, ValueError):
                return False, f"{k} phải là số."
            if v <= 0 or v > float(eff[k]):
                return False, f"{policy.LABELS.get(k, k)}: chỉ được hạ (≤ {float(eff[k]):,.0f}). Muốn nâng hãy liên hệ chi nhánh."
            new[k] = v
        elif k in ("hours_from", "hours_to"):
            new[k] = int(v)
    allv = dict(a["limits"])
    allv[domain] = new
    db.execute("UPDATE agents SET limits=? WHERE agent_id=?", (db.jdump(allv), agent_id))
    return True, "OK"


# ---- API key ----
def issue_key(agent_id):
    a = get(agent_id)
    if not a or a["status"] not in ("ACTIVE", "PAUSED", "SUSPENDED"):
        return None
    prefix = secrets.token_hex(4)
    secret = secrets.token_urlsafe(30)
    key = f"agk_{prefix}_{secret}"
    db.execute("UPDATE agents SET key_hash=?, key_prefix=? WHERE agent_id=?", (_h(key), prefix, agent_id))
    return key


def by_key(key: str):
    m = re.fullmatch(r"agk_([0-9a-f]{8})_[A-Za-z0-9_\-]{20,64}", key or "")
    if not m:
        return None
    r = _dec(db.one("SELECT * FROM agents WHERE key_prefix=?", (m.group(1),)))
    if r and r.get("key_hash") and hmac.compare_digest(r["key_hash"], _h(key)):
        return r
    return None


def is_usable(a):
    """Điều kiện pháp lý để giao dịch."""
    if not a:
        return False, "Agent chưa đăng ký với ngân hàng"
    if a["status"] == "PENDING":
        return False, "Hồ sơ đăng ký Agent đang chờ chi nhánh phê duyệt"
    if a["status"] == "REJECTED":
        return False, "Hồ sơ đăng ký Agent đã bị từ chối"
    if a["status"] == "REVOKED":
        return False, "Agent đã bị thu hồi"
    if a["status"] == "SUSPENDED":
        return False, "Agent đang bị ngân hàng đình chỉ"
    if a["status"] == "PAUSED":
        return False, "Agent đang được khách hàng tạm dừng"
    if a.get("valid_until") and a["valid_until"] < store.now():
        return False, "Đăng ký Agent đã hết hiệu lực – cần gia hạn"
    return True, "OK"
