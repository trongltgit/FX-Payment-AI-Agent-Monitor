"""Blueprint /api/agent/* – dùng chung phiên, CSRF, fingerprint, rate-limit của Anti-Bot (cổng guard.py chạy trước)."""
import time
from functools import wraps

from flask import Blueprint, abort, jsonify, make_response, request, session

from agentmon import cards, critic, db, engine, kya, lab, ml, policy, registry, reports
from app.customer.mock_db import (DEMO_CUSTOMERS, get_demo_customer, list_demo_customers_by_ids)
from services.audit_log import add_log
from utils import store
from utils import totp as totp_mod
from utils.rate_limit import custom_rate_limit
from utils.security import get_client_ip

agent_bp = Blueprint("agentmon", __name__)
STAFF = {"PNV", "STAFF", "BRANCH", "CN_ADMIN"}


def role():
    return (session.get("role") or "").upper()


def uid():
    return session.get("user_id") or ""


def scope():
    """None = tất cả (TSC); ngược lại tập customer_id được phép."""
    r = role()
    if r == "HQ":
        return None
    if r == "CUSTOMER":
        return {session.get("customer_id")} if session.get("customer_id") else set()
    return set(session.get("permitted_customers") or [])


def allowed(cid):
    s = scope()
    return s is None or cid in s


def err(code, msg, status=400, **kw):
    d = {"error": code, "message": msg}
    d.update(kw)
    return jsonify(d), status


def roles(*rs):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            if not session.get("user_id"):
                return err("AUTHENTICATION_REQUIRED", "Yêu cầu đăng nhập.", 401)
            if role() not in rs and not (("STAFF" in rs) and role() in STAFF):
                return err("FORBIDDEN", "Vai trò hiện tại không có quyền thao tác này.", 403)
            return f(*a, **k)
        return w
    return deco


def body():
    return request.get_json(silent=True) or {}


def customer_id_param(required=True):
    """Khách hàng: luôn là chính mình. Nhân viên/TSC: tham số customer_id phải nằm trong phạm vi."""
    if role() == "CUSTOMER":
        return session.get("customer_id")
    cid = (request.args.get("customer_id") or body().get("customer_id") or "").strip()
    if not cid:
        return None
    if not allowed(cid):
        abort(make_response(err("FORBIDDEN", "Khách hàng ngoài phạm vi phụ trách của bạn.", 403)))
    return cid


# ---------------------------------------------------------------- meta
@agent_bp.route("/meta", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def meta():
    s = scope()
    ids = list(DEMO_CUSTOMERS) if s is None else sorted(s)
    custs = [{"customer_id": c["customer_id"], "name": c["customer_name"], "segment": c["segment"], "branch_id": c["branch_id"],
              "online": c["online"]} for c in list_demo_customers_by_ids(ids)]
    return jsonify({"role": role(), "customers": custs, "pairs": policy.FX_PAIRS, "lab_enabled": lab.enabled(),
                    "kill_switch": policy.kill_switch(), "labels": policy.LABELS, "num_keys": policy.NUM_KEYS,
                    "consent": {"version": registry.CONSENT_VERSION, "text": registry.CONSENT_TEXT},
                    "demo": lab.enabled()})


@agent_bp.route("/overview", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def overview():
    dom = request.args.get("domain", "FX").upper()
    if dom not in ("FX", "PAY"):
        return err("INVALID", "domain phải là FX hoặc PAY")
    cid = customer_id_param()
    if cid is False:
        return err("FORBIDDEN", "Khách hàng ngoài phạm vi.", 403)
    days = max(1, min(int(request.args.get("days", 30) or 30), 365))
    return jsonify(reports.overview(dom, scope(), days, cid))


@agent_bp.route("/actions", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def actions():
    cid = customer_id_param()
    if cid is False:
        return err("FORBIDDEN", "Khách hàng ngoài phạm vi.", 403)
    rows = reports.list_actions(scope(), request.args.get("domain") or None, cid, request.args.get("decision") or None,
                                request.args.get("status") or None, request.args.get("limit", 100), request.args.get("offset", 0),
                                request.args.get("history", "1") != "0")
    return jsonify({"actions": [reports.view(r, role()) for r in rows]})


@agent_bp.route("/actions/<int:aid>", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def action_detail(aid):
    r = db.one("SELECT * FROM actions WHERE id=?", (aid,))
    if not r or not allowed(r["customer_id"]):
        return err("NOT_FOUND", "Không tìm thấy giao dịch.", 404)
    r = reports.decode(r)
    d = reports.view(r, role())
    if r.get("kya_id"):
        d["kya"] = db.one("SELECT id,status,created_at,expires_at,decided_at,method,attempts FROM kya WHERE id=?", (r["kya_id"],))
    return jsonify({"action": d})


@agent_bp.route("/profile", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def profile():
    cid = customer_id_param()
    if not cid:
        return err("INVALID", "Thiếu hoặc sai customer_id.")
    p = reports.profile(cid)
    return jsonify({"profile": p, "cards": [cards.public_view(c) | {"token": None} for c in db.query("SELECT * FROM cards WHERE customer_id=?", (cid,))]})


@agent_bp.route("/agents", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def agents():
    cid = customer_id_param()
    if cid is False:
        return err("FORBIDDEN", "Khách hàng ngoài phạm vi.", 403)
    s = scope() if not cid else {cid}
    return jsonify({"agents": registry.list_agents(None if s is None else list(s), request.args.get("status") or None)})


# ---------------------------------------------------------------- khách hàng
@agent_bp.route("/me/agents/register", methods=["POST"])
@custom_rate_limit("10 per hour")
@roles("CUSTOMER")
def me_register():
    d = body()
    cid = session.get("customer_id")
    if not d.get("consent"):
        return err("CONSENT_REQUIRED", "Bạn phải đồng ý điều khoản pháp lý khi đăng ký AI Agent.")
    a = kya.get_auth(cid)
    if not a or not a.get("totp_secret"):
        return err("AUTHENTICATOR_REQUIRED", "Cần đăng ký ứng dụng Authenticator trước khi đăng ký AI Agent (để xác minh KYA).")
    if not totp_mod.verify(cid, a["totp_secret"], str(d.get("totp", ""))):
        return err("OTP_INVALID", "Mã OTP Authenticator không đúng.", 401)
    cust = get_demo_customer(cid)
    ok, msg, aid = registry.register(cust, d.get("name"), d.get("purpose"), d.get("domains"), d.get("kinds"),
                                     d.get("requested_limits"), get_client_ip())
    if not ok:
        return err("INVALID", msg)
    add_log("agent_registered", user_id=uid(), role="CUSTOMER", customer_id=cid, branch_id=cust["branch_id"], detail={"agent_id": aid})
    return jsonify({"status": "success", "agent_id": aid, "message": "Đã gửi hồ sơ đăng ký tới chi nhánh. Agent chỉ hoạt động sau khi được duyệt."})


def _own_agent(aid):
    a = registry.get(aid)
    return a if a and a["customer_id"] == session.get("customer_id") else None


@agent_bp.route("/me/agents/<aid>/status", methods=["POST"])
@roles("CUSTOMER")
def me_status(aid):
    a = _own_agent(aid)
    if not a:
        return err("NOT_FOUND", "Không tìm thấy Agent.", 404)
    st = str(body().get("status", "")).upper()
    if st not in ("PAUSED", "ACTIVE", "REVOKED"):
        return err("INVALID", "Trạng thái phải là PAUSED, ACTIVE hoặc REVOKED.")
    if st == "ACTIVE" and a["status"] != "PAUSED":
        return err("INVALID", "Chỉ khôi phục được Agent do chính bạn tạm dừng (Agent bị ngân hàng đình chỉ phải liên hệ chi nhánh).")
    ok, msg = registry.set_status(aid, st, "Khách hàng thao tác", uid())
    if not ok:
        return err("INVALID", msg)
    add_log("agent_status", user_id=uid(), customer_id=a["customer_id"], detail={"agent_id": aid, "status": st})
    return jsonify({"status": "success"})


@agent_bp.route("/me/agents/<aid>/limits", methods=["POST"])
@roles("CUSTOMER")
def me_limits(aid):
    a = _own_agent(aid)
    d = body()
    if not a:
        return err("NOT_FOUND", "Không tìm thấy Agent.", 404)
    ok, msg = registry.lower_limits(aid, str(d.get("domain", "")).upper(), d.get("values") or {})
    return (jsonify({"status": "success"}) if ok else err("INVALID", msg))


@agent_bp.route("/me/agents/<aid>/api-key", methods=["POST"])
@custom_rate_limit("5 per hour")
@roles("CUSTOMER")
def me_key(aid):
    a = _own_agent(aid)
    if not a:
        return err("NOT_FOUND", "Không tìm thấy Agent.", 404)
    au = kya.get_auth(a["customer_id"])
    if not au or not totp_mod.verify(a["customer_id"], au["totp_secret"], str(body().get("totp", ""))):
        return err("OTP_INVALID", "Cần mã OTP Authenticator hợp lệ để cấp API key.", 401)
    key = registry.issue_key(aid)
    if not key:
        return err("INVALID", "Chỉ cấp key cho Agent đã được duyệt.")
    add_log("agent_key_issued", user_id=uid(), customer_id=a["customer_id"], level="warn", detail={"agent_id": aid})
    return jsonify({"status": "success", "api_key": key, "warning": "Khóa chỉ hiển thị MỘT lần. Cấp lại sẽ vô hiệu khóa cũ."})


@agent_bp.route("/me/authenticator", methods=["GET"])
@roles("CUSTOMER")
def me_auth():
    cid = session.get("customer_id")
    a = kya.get_auth(cid)
    out = {"enrolled": bool(a and a.get("totp_secret")), "device_paired": bool(a and a.get("device_hash")),
           "device_label": a.get("device_label") if a else None, "paired_at": a.get("paired_at") if a else None}
    if lab.enabled() and out["enrolled"]:
        out["demo_totp_now"] = totp_mod.totp_now(a["totp_secret"])
    return jsonify(out)


@agent_bp.route("/me/authenticator/start", methods=["POST"])
@custom_rate_limit("10 per hour")
@roles("CUSTOMER")
def me_auth_start():
    cid = session.get("customer_id")
    r = kya.start_pairing(cid)
    add_log("authenticator_pairing_started", user_id=uid(), customer_id=cid, level="warn")
    return jsonify({"status": "success", **r})


@agent_bp.route("/me/authenticator/unpair", methods=["POST"])
@roles("CUSTOMER")
def me_auth_unpair():
    kya.unpair(session.get("customer_id"))
    return jsonify({"status": "success"})


@agent_bp.route("/me/kya/pending", methods=["GET"])
@roles("CUSTOMER")
def me_kya_pending():
    return jsonify({"pending": kya.pending_for(session.get("customer_id"))})


@agent_bp.route("/me/kya/<kid>/approve", methods=["POST"])
@custom_rate_limit("20 per minute")
@roles("CUSTOMER")
def me_kya_approve(kid):
    ok, msg, res = kya.approve_totp(session.get("customer_id"), kid, str(body().get("code", "")))
    if not ok:
        return err("KYA_FAILED", msg, 400)
    add_log("kya_approved", user_id=uid(), customer_id=session.get("customer_id"), detail={"kya": kid, "result": res})
    return jsonify({"status": "success", "result": res})


@agent_bp.route("/me/kya/<kid>/deny", methods=["POST"])
@roles("CUSTOMER")
def me_kya_deny(kid):
    ok, msg, res = kya.deny_portal(session.get("customer_id"), kid)
    if not ok:
        return err("KYA_FAILED", msg, 400)
    add_log("kya_denied", user_id=uid(), customer_id=session.get("customer_id"), level="warn", detail={"kya": kid})
    return jsonify({"status": "success", "result": res})


@agent_bp.route("/me/cards", methods=["GET"])
@roles("CUSTOMER")
def me_cards():
    return jsonify({"cards": [cards.public_view(c) for c in db.query("SELECT * FROM cards WHERE customer_id=?", (session.get("customer_id"),))]})


@agent_bp.route("/cards/validate", methods=["POST"])
@custom_rate_limit("30 per minute")
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def cards_validate():
    ok, msg, net = cards.validate_pan(str(body().get("pan", "")))
    pan = cards.normalize_pan(str(body().get("pan", "")))
    return jsonify({"valid": ok, "message": msg, "network": net,
                    "masked": cards.mask(pan[:6], pan[-4:]) if ok else None})


@agent_bp.route("/me/cards", methods=["POST"])
@custom_rate_limit("10 per hour")
@roles("CUSTOMER")
def me_cards_add():
    d = body()
    cid = session.get("customer_id")
    ok, msg, c = cards.add_card(cid, str(d.get("pan", "")), d.get("holder"), d.get("exp_month"), d.get("exp_year"),
                                _opt(d.get("per_txn_limit")), _opt(d.get("daily_limit")), bool(d.get("cnp_enabled", True)),
                                bool(d.get("intl_enabled", False)))
    if not ok:
        return err("CARD_INVALID", msg)
    add_log("card_added", user_id=uid(), customer_id=cid, detail={"card_id": c["card_id"], "network": c["network"], "last4": c["masked"][-4:]})
    return jsonify({"status": "success", "card": c})


def _opt(v):
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


@agent_bp.route("/me/cards/<card_id>", methods=["POST"])
@roles("CUSTOMER")
def me_card_update(card_id):
    c = db.one("SELECT * FROM cards WHERE card_id=? AND customer_id=?", (card_id, session.get("customer_id")))
    if not c:
        return err("NOT_FOUND", "Không tìm thấy thẻ.", 404)
    d = body()
    st = c["status"]
    if "status" in d:
        if d["status"] not in ("ACTIVE", "FROZEN"):
            return err("INVALID", "Khách chỉ được ACTIVE/FROZEN.")
        if c["status"] == "BLOCKED":
            return err("INVALID", "Thẻ bị ngân hàng khóa.")
        st = d["status"]
    db.execute("UPDATE cards SET status=?, cnp_enabled=?, intl_enabled=?, per_txn_limit=COALESCE(?,per_txn_limit), daily_limit=COALESCE(?,daily_limit) WHERE card_id=?",
               (st, 1 if d.get("cnp_enabled", c["cnp_enabled"]) else 0, 1 if d.get("intl_enabled", c["intl_enabled"]) else 0,
                _opt(d.get("per_txn_limit")), _opt(d.get("daily_limit")), card_id))
    return jsonify({"status": "success"})


@agent_bp.route("/me/beneficiaries", methods=["GET", "POST"])
@roles("CUSTOMER")
def me_benef():
    cid = session.get("customer_id")
    if request.method == "POST":
        acc = str(body().get("account", "")).strip()
        if not acc.isdigit() or not 6 <= len(acc) <= 20:
            return err("INVALID", "Số tài khoản 6–20 chữ số.")
        db.execute("INSERT OR REPLACE INTO trusted_beneficiaries(customer_id,account,bank,added_at) VALUES(?,?,?,?)",
                   (cid, acc, str(body().get("bank", ""))[:20], store.now()))
    rows = db.query("SELECT account, bank, added_at FROM trusted_beneficiaries WHERE customer_id=?", (cid,))
    for r in rows:
        r["account"] = "***" + r["account"][-4:]
    return jsonify({"beneficiaries": rows})


# ---------------------------------------------------------------- chi nhánh
@agent_bp.route("/cn/registrations/<aid>/approve", methods=["POST"])
@roles("CN_ADMIN", "HQ")
def cn_approve(aid):
    a = registry.get(aid)
    if not a or not allowed(a["customer_id"]):
        return err("NOT_FOUND", "Không tìm thấy hồ sơ.", 404)
    d = body()
    ok, msg = registry.approve(aid, uid(), d.get("limits") or {}, int(d.get("valid_days") or 365))
    if not ok:
        return err("INVALID", msg)
    add_log("agent_approved", user_id=uid(), role=role(), customer_id=a["customer_id"], branch_id=a["branch_id"] or "", detail={"agent_id": aid})
    return jsonify({"status": "success", "agent": registry.public(registry.get(aid))})


@agent_bp.route("/cn/registrations/<aid>/reject", methods=["POST"])
@roles("CN_ADMIN", "HQ")
def cn_reject(aid):
    a = registry.get(aid)
    if not a or not allowed(a["customer_id"]):
        return err("NOT_FOUND", "Không tìm thấy hồ sơ.", 404)
    ok, msg = registry.reject(aid, uid(), str(body().get("reason", "")))
    return jsonify({"status": "success"}) if ok else err("INVALID", msg)


@agent_bp.route("/cn/agents/<aid>/status", methods=["POST"])
@roles("CN_ADMIN", "HQ")
def cn_agent_status(aid):
    a = registry.get(aid)
    if not a or not allowed(a["customer_id"]):
        return err("NOT_FOUND", "Không tìm thấy Agent.", 404)
    d = body()
    ok, msg = registry.set_status(aid, str(d.get("status", "")).upper(), str(d.get("note", ""))[:100], uid())
    if ok:
        add_log("agent_status", user_id=uid(), role=role(), customer_id=a["customer_id"], level="warn",
                detail={"agent_id": aid, "status": d.get("status")})
    return jsonify({"status": "success"}) if ok else err("INVALID", msg)


@agent_bp.route("/cn/limits", methods=["GET", "POST"])
@roles("CN_ADMIN", "HQ", "PNV", "STAFF")
def cn_limits():
    cid = customer_id_param()
    dom = (request.args.get("domain") or body().get("domain") or "FX").upper()
    if not cid or dom not in ("FX", "PAY"):
        return err("INVALID", "Thiếu/sai customer_id hoặc domain.")
    cust = get_demo_customer(cid)
    if request.method == "POST":
        if role() not in ("CN_ADMIN", "HQ"):
            return err("FORBIDDEN", "Chỉ Admin CN hoặc TSC đặt hạn mức.", 403)
        ok, msg, clean = policy.set_cn_limits(cid, dom, cust["segment"], body().get("values") or {}, uid())
        if not ok:
            return err("LIMIT_EXCEEDS_TSC", msg)
        add_log("agent_limits_set", user_id=uid(), role=role(), customer_id=cid, branch_id=cust["branch_id"], detail={"domain": dom, "values": clean})
    tsc = policy.get_tsc(dom)["segments"].get(cust["segment"], {})
    eff = {k: v for k, v in policy.effective_limits(dom, cust["segment"], cid, None).items() if k != "_global"}
    return jsonify({"domain": dom, "segment": cust["segment"], "tsc_cap": tsc, "cn_override": policy.get_cn_limits(cid, dom), "effective": eff})


@agent_bp.route("/cn/review-queue", methods=["GET"])
@roles("CN_ADMIN", "HQ", "PNV", "STAFF")
def review_queue():
    rows = reports.list_actions(scope(), None, None, None, "REVIEW_PENDING", 100, 0)
    return jsonify({"queue": [reports.view(r, role()) for r in rows]})


@agent_bp.route("/cn/review/<int:aid>", methods=["POST"])
@custom_rate_limit("60 per minute")
@roles("CN_ADMIN", "HQ", "PNV", "STAFF")
def review(aid):
    r = db.one("SELECT customer_id FROM actions WHERE id=?", (aid,))
    if not r or not allowed(r["customer_id"]):
        return err("NOT_FOUND", "Không tìm thấy giao dịch.", 404)
    d = body()
    ok, msg = engine.review_action(aid, uid(), bool(d.get("approve")), str(d.get("note", "")))
    add_log("agent_review", user_id=uid(), role=role(), customer_id=r["customer_id"], level="warn",
            detail={"action_id": aid, "approve": bool(d.get("approve")), "ok": ok})
    return jsonify({"status": "success", "message": msg}) if ok else err("REVIEW_FAILED", msg)


@agent_bp.route("/cn/cards", methods=["GET"])
@roles("CN_ADMIN", "HQ", "PNV", "STAFF")
def cn_cards():
    s = scope()
    rows = db.query("SELECT * FROM cards ORDER BY customer_id")
    return jsonify({"cards": [cards.public_view(c) | {"token": None} for c in rows if s is None or c["customer_id"] in s]})


@agent_bp.route("/cn/cards/<card_id>/status", methods=["POST"])
@roles("CN_ADMIN", "HQ")
def cn_card_status(card_id):
    c = db.one("SELECT * FROM cards WHERE card_id=?", (card_id,))
    st = str(body().get("status", "")).upper()
    if not c or not allowed(c["customer_id"]) or st not in ("ACTIVE", "FROZEN", "BLOCKED"):
        return err("INVALID", "Thẻ/trạng thái không hợp lệ.")
    db.execute("UPDATE cards SET status=? WHERE card_id=?", (st, card_id))
    add_log("card_status", user_id=uid(), role=role(), customer_id=c["customer_id"], level="warn", detail={"card_id": card_id, "status": st})
    return jsonify({"status": "success"})


@agent_bp.route("/cn/flags/clear", methods=["POST"])
@roles("CN_ADMIN", "HQ")
def clear_flags():
    cid = customer_id_param()
    if not cid:
        return err("INVALID", "customer_id không hợp lệ.")
    db.execute("INSERT INTO flags(customer_id,suspicion,watchlist,updated_at) VALUES(?,0,0,?) ON CONFLICT(customer_id) DO UPDATE SET suspicion=0, watchlist=0, updated_at=excluded.updated_at", (cid, store.now()))
    return jsonify({"status": "success"})


# ---------------------------------------------------------------- TSC
@agent_bp.route("/hq/policy/<domain>", methods=["GET", "POST"])
@roles("HQ")
def hq_policy(domain):
    domain = domain.upper()
    if domain not in ("FX", "PAY"):
        return err("INVALID", "Domain không hợp lệ.")
    if request.method == "POST":
        ok, msg = policy.set_tsc(domain, body(), uid())
        if not ok:
            return err("INVALID", msg)
        add_log("agent_policy_set", user_id=uid(), role="HQ", level="warn", detail={"domain": domain})
    return jsonify({"domain": domain, "policy": policy.get_tsc(domain), "labels": policy.LABELS})


@agent_bp.route("/hq/killswitch", methods=["GET", "POST"])
@roles("HQ")
def hq_kill():
    if request.method == "POST":
        d = body()
        policy.set_kill_switch(bool(d.get("on")), str(d.get("reason", ""))[:120], uid())
        add_log("agent_killswitch", user_id=uid(), role="HQ", level="critical", detail={"on": bool(d.get("on")), "reason": d.get("reason")})
    return jsonify(policy.kill_switch())


@agent_bp.route("/hq/model", methods=["GET"])
@roles("HQ")
def hq_model():
    return jsonify({"models": ml.status(), "llm": critic.status()})


@agent_bp.route("/hq/model/retrain", methods=["POST"])
@custom_rate_limit("3 per hour")
@roles("HQ")
def hq_retrain():
    out = {d: ml.train(d) for d in ("FX", "PAY")}
    add_log("agent_model_retrain", user_id=uid(), role="HQ", level="warn")
    return jsonify({"status": "success", "models": out})


@agent_bp.route("/hq/reseed", methods=["POST"])
@roles("HQ")
def hq_reseed():
    if not lab.enabled():
        return err("FORBIDDEN", "Chỉ dùng ở môi trường demo.", 403)
    from agentmon import seed
    seed.seed(force=True)
    return jsonify({"status": "success"})


# ---------------------------------------------------------------- Test Lab
@agent_bp.route("/lab/scenarios", methods=["GET"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def lab_scen():
    if not lab.enabled():
        return err("FORBIDDEN", "Test Lab đã tắt ở production.", 403)
    return jsonify({"scenarios": lab.catalog(request.args.get("domain") or None)})


@agent_bp.route("/lab/run", methods=["POST"])
@custom_rate_limit("60 per minute")
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def lab_run():
    if not lab.enabled():
        return err("FORBIDDEN", "Test Lab đã tắt ở production.", 403)
    cid = customer_id_param()
    if not cid:
        return err("INVALID", "Chọn khách hàng hợp lệ trong phạm vi của bạn.")
    r = lab.run(str(body().get("scenario", "")), cid, get_client_ip())
    if r.get("error"):
        return err("LAB_ERROR", r["error"])
    return jsonify(r)


@agent_bp.route("/lab/custom", methods=["POST"])
@custom_rate_limit("60 per minute")
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def lab_custom():
    """Gửi 1 giao dịch tự soạn như một Agent (qua đúng pipeline)."""
    if not lab.enabled():
        return err("FORBIDDEN", "Test Lab đã tắt ở production.", 403)
    cid = customer_id_param()
    if not cid:
        return err("INVALID", "Chọn khách hàng hợp lệ.")
    d = body()
    ag = registry.get(str(d.get("agent_id", "")))
    if ag and ag["customer_id"] != cid:
        return err("FORBIDDEN", "Agent không thuộc khách hàng này.", 403)
    try:
        r = engine.evaluate(d.get("payload") or {}, str(d.get("agent_id", "")), source="LAB", customer_hint=cid,
                            sim_hour=d.get("sim_hour"), ip=get_client_ip())
    except engine.BadRequest as e:
        return err("BAD_REQUEST", str(e))
    return jsonify({"result": reports.view(reports.decode(db.one("SELECT * FROM actions WHERE id=?", (r["action_id"],))), role())})


@agent_bp.route("/lab/topup", methods=["POST"])
@roles("HQ", "CN_ADMIN", "PNV", "STAFF", "CUSTOMER")
def lab_topup():
    if not lab.enabled():
        return err("FORBIDDEN", "Chỉ ở demo.", 403)
    cid = customer_id_param()
    if not cid:
        return err("INVALID", "Chọn khách hàng hợp lệ.")
    try:
        amt = float(body().get("amount", 1_000_000_000))
    except (TypeError, ValueError):
        return err("INVALID", "Số tiền không hợp lệ.")
    lab.topup(cid, max(0, min(amt, 1e13)))
    return jsonify({"status": "success", "balance": amt})
