"""Truy vấn tổng hợp cho dashboard Monitor + hồ sơ hành vi khách hàng."""
import time

from agentmon import db, engine, features as F, policy
from utils import store


def _scope_sql(cids, col="customer_id"):
    if cids is None:
        return "1=1", []
    if not cids:
        return "0=1", []
    return f"{col} IN ({','.join('?' * len(cids))})", list(cids)


def overview(domain, cids, days=30, customer_id=None):
    now = store.now()
    since = now - days * 86400
    sc, args = _scope_sql(cids)
    where = f"{sc} AND domain=? AND ts>?"
    args = args + [domain, since]
    if customer_id:
        where += " AND customer_id=?"
        args.append(customer_id)
    by_dec = {r["decision"]: r["n"] for r in db.query(f"SELECT decision, COUNT(*) n FROM actions WHERE {where} GROUP BY decision", args)}
    by_st = {r["status"]: r["n"] for r in db.query(f"SELECT status, COUNT(*) n FROM actions WHERE {where} GROUP BY status", args)}
    unit = "amount_usd" if domain == "FX" else "amount_vnd"
    vol = db.one(f"SELECT COALESCE(SUM({unit}),0) v FROM actions WHERE {where} AND status='EXECUTED'", args)["v"]
    vol_blocked = db.one(f"SELECT COALESCE(SUM({unit}),0) v FROM actions WHERE {where} AND status IN ('BLOCKED','DENIED_BY_CUSTOMER','REJECTED_BY_STAFF')", args)["v"]
    daily = db.query(f"SELECT CAST((ts+25200)/86400 AS INTEGER) d, decision, COUNT(*) n FROM actions WHERE {where} GROUP BY d, decision ORDER BY d", args)
    series = {}
    for r in daily:
        series.setdefault(r["d"], {"ALLOW": 0, "KYA": 0, "REVIEW": 0, "BLOCK": 0})[r["decision"]] = r["n"]
    ser = [{"day": time.strftime("%d/%m", time.gmtime(d * 86400)), **v} for d, v in sorted(series.items())]
    hist = [0] * 5
    for r in db.query(f"SELECT final_risk FROM actions WHERE {where} AND final_risk IS NOT NULL", args):
        hist[min(int(r["final_risk"] * 5), 4)] += 1
    trig = {}
    for r in db.query(f"SELECT triggers FROM actions WHERE {where} AND triggers!='[]' ORDER BY ts DESC LIMIT 400", args):
        for t in db.jload(r["triggers"], []):
            trig[t[0]] = trig.get(t[0], 0) + 1
    sc2, a2 = _scope_sql(cids)
    pend = db.one(f"SELECT COUNT(*) n FROM actions WHERE {sc2} AND domain=? AND status='PENDING_KYA'", a2 + [domain])["n"]
    rev = db.one(f"SELECT COUNT(*) n FROM actions WHERE {sc2} AND domain=? AND status='REVIEW_PENDING'", a2 + [domain])["n"]
    sc3, a3 = _scope_sql(cids, "customer_id")
    watch = db.query(f"SELECT customer_id, suspicion, watchlist FROM flags WHERE {sc3} AND suspicion>0 ORDER BY suspicion DESC LIMIT 8", a3)
    ag = {r["status"]: r["n"] for r in db.query(f"SELECT status, COUNT(*) n FROM agents WHERE {sc3} GROUP BY status", a3)}
    return {"domain": domain, "days": days, "unit": "USD" if domain == "FX" else "VND", "total": sum(by_dec.values()),
            "by_decision": by_dec, "by_status": by_st, "volume_executed": vol, "volume_stopped": vol_blocked,
            "series": ser, "risk_hist": hist, "top_triggers": sorted(trig.items(), key=lambda x: -x[1])[:8],
            "pending_kya": pend, "review_queue": rev, "watchlist": watch, "agents_by_status": ag}


def list_actions(cids, domain=None, customer_id=None, decision=None, status=None, limit=100, offset=0, include_history=True):
    sc, args = _scope_sql(cids)
    w = [sc]
    if domain:
        w.append("domain=?"); args.append(domain)
    if customer_id:
        w.append("customer_id=?"); args.append(customer_id)
    if decision:
        w.append("decision=?"); args.append(decision)
    if status:
        w.append("status=?"); args.append(status)
    if not include_history:
        w.append("source!='SEED'")
    limit = max(1, min(int(limit), 300))
    rows = db.query(f"SELECT * FROM actions WHERE {' AND '.join(w)} ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?", args + [limit, int(offset)])
    return [decode(r) for r in rows]


def decode(r):
    for k in ("details", "reasons", "triggers", "llm"):
        r[k] = db.jload(r.get(k), [] if k in ("reasons", "triggers") else None)
    return r


def view(r, role):
    """Khách hàng không thấy điểm nội bộ / LLM (tránh dò ngưỡng); nhân viên & TSC thấy đầy đủ."""
    keep = ["id", "ts", "domain", "kind", "customer_id", "branch_id", "agent_id", "channel", "amount_vnd", "amount_usd", "pair", "side",
            "leverage", "merchant", "mcc", "country", "card_id", "hour", "decision", "status", "reason_public", "kya_id", "executed_at",
            "reviewer", "review_note", "source"]
    d = {k: r.get(k) for k in keep}
    ben = r.get("beneficiary")
    d["beneficiary"] = ("***" + ben[-4:]) if (ben and role == "CUSTOMER") else ben
    d["triggers"] = [t[1] if isinstance(t, (list, tuple)) and len(t) > 1 else t for t in (r.get("triggers") or [])]
    d["hard_reason"] = r.get("hard_reason")
    if role != "CUSTOMER":
        d.update(anomaly=r.get("anomaly"), behavior=r.get("behavior"), velocity=r.get("velocity"), final_risk=r.get("final_risk"),
                 reasons=r.get("reasons"), llm=r.get("llm"), trigger_codes=[t[0] for t in (r.get("triggers") or []) if isinstance(t, (list, tuple))])
    else:
        d["reasons"] = [x for x in (r.get("reasons") or []) if r.get("hard_reason")]
    return d


def profile(customer_id):
    from app.customer.mock_db import get_demo_customer
    cust = get_demo_customer(customer_id)
    if not cust:
        return None
    out = {"customer_id": customer_id, "name": cust["customer_name"], "segment": cust["segment"], "branch_id": cust["branch_id"],
           "online": cust["online"], "status": cust["status"]}
    bal, avail = engine.available_balance(customer_id)
    out["balance_vnd"], out["available_vnd"] = bal, avail
    fl = db.one("SELECT * FROM flags WHERE customer_id=?", (customer_id,)) or {}
    out["suspicion"], out["watchlist"] = float(fl.get("suspicion") or 0), bool(fl.get("watchlist"))
    now = store.now()
    last = db.one("SELECT MAX(ts) m FROM actions WHERE customer_id=? AND status='EXECUTED'", (customer_id,))["m"]
    onl = db.one("SELECT COUNT(*) n, MIN(ts) f FROM actions WHERE customer_id=? AND status='EXECUTED' AND channel IN ('AGENT','ONLINE')", (customer_id,))
    out["online_history"] = {"count": onl["n"], "first_ts": onl["f"], "is_first_time": onl["n"] == 0}
    out["days_since_last_txn"] = round((now - last) / 86400, 1) if last else None
    out["domains"] = {}
    for dom in ("FX", "PAY"):
        hist = db.query("SELECT * FROM actions WHERE customer_id=? AND domain=? AND status='EXECUTED' ORDER BY ts DESC LIMIT 600", (customer_id, dom))
        ctx = F.Ctx(dom, now, hist)
        st = F._stats(ctx, None)
        d = {"n": len(hist), "avg": round(st["mean"], 2), "std": round(st["std"], 2),
             "typical_hours": sorted(st["typical_hours"]), "max": max([F.amt_of(h, dom) for h in hist], default=0)}
        if dom == "FX":
            d["pairs"] = sorted(st["pairs"]); d["avg_leverage"] = round(st["lev_mean"], 2)
        else:
            d["beneficiaries"] = len(st["benef"]); d["merchants"] = len(st["merch"]); d["countries"] = sorted(c for c in st["countries"] if c)
            kinds = {}
            for h in hist:
                kinds[h["kind"]] = kinds.get(h["kind"], 0) + 1
            d["by_kind"] = kinds
        out["domains"][dom] = d
        agent_lim = {}
        out.setdefault("limits", {})[dom] = {k: v for k, v in policy.effective_limits(dom, cust["segment"], customer_id, None).items() if k != "_global"}
    return out
