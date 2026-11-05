"""
Chính sách & hạn mức PHÂN CẤP (giống mô hình TSC → Chi nhánh → Khách hàng của Anti-Bot):

    TSC (trần theo phân khúc)  ≥  Chi nhánh (hạn mức riêng từng CIF)  ≥  Hạn mức do KH đăng ký cho Agent

Hạn mức hiệu lực = MIN của ba cấp. Hard policy dùng hạn mức này và KHÔNG thể bị ML/LLM ghi đè.
"""
import copy

from agentmon import db

FX_PAIRS = ["USDVND", "EURVND", "GBPVND", "JPYVND", "AUDVND", "SGDVND",
            "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDSGD"]

DEFAULT_FX = {
    "global": {"kya_threshold": 0.35, "review_threshold": 0.65, "block_threshold": 0.85,
               "kya_ttl_seconds": 180, "max_pending_kya": 5, "probation_actions": 3,
               "dormant_days": 60, "balance_drain_pct": 0.70, "usd_vnd": 26200},
    "segments": {
        "STANDARD": {"per_order_usd": 20000, "daily_usd": 60000, "max_leverage": 10, "per_hour": 10, "per_day": 40,
                     "kya_above_usd": 8000, "allowed_pairs": ["USDVND", "EURVND", "EURUSD", "GBPUSD", "USDJPY"]},
        "VIP": {"per_order_usd": 100000, "daily_usd": 400000, "max_leverage": 20, "per_hour": 20, "per_day": 120,
                "kya_above_usd": 50000, "allowed_pairs": FX_PAIRS},
        "CORPORATE": {"per_order_usd": 500000, "daily_usd": 2000000, "max_leverage": 10, "per_hour": 30, "per_day": 200,
                      "kya_above_usd": 300000, "allowed_pairs": FX_PAIRS},
    },
}

DEFAULT_PAY = {
    "global": {"kya_threshold": 0.35, "review_threshold": 0.65, "block_threshold": 0.85,
               "kya_ttl_seconds": 180, "max_pending_kya": 5, "probation_actions": 3,
               "dormant_days": 60, "balance_drain_pct": 0.70, "cnp_3ds_above_vnd": 5_000_000,
               "blocked_mcc": ["7995", "6051"], "high_risk_mcc": ["5967", "5816", "6540", "4829", "6012"],
               "blocked_countries": ["KP", "IR", "SY", "CU"],
               "high_risk_countries": ["NG", "RU", "BY", "MM", "VE", "PK"],
               "blocked_accounts": ["9999999999", "0000000000"]},
    "segments": {
        "STANDARD": {"transfer_per_txn": 50_000_000, "transfer_daily": 200_000_000, "transfer_monthly": 1_000_000_000,
                     "card_per_txn": 30_000_000, "card_daily": 100_000_000, "online_per_txn": 20_000_000,
                     "per_hour": 15, "per_day": 60, "kya_above": 10_000_000, "new_beneficiary_kya_above": 2_000_000},
        "VIP": {"transfer_per_txn": 500_000_000, "transfer_daily": 2_000_000_000, "transfer_monthly": 10_000_000_000,
                "card_per_txn": 200_000_000, "card_daily": 500_000_000, "online_per_txn": 100_000_000,
                "per_hour": 30, "per_day": 150, "kya_above": 50_000_000, "new_beneficiary_kya_above": 10_000_000},
        "CORPORATE": {"transfer_per_txn": 5_000_000_000, "transfer_daily": 20_000_000_000,
                      "transfer_monthly": 200_000_000_000, "card_per_txn": 500_000_000, "card_daily": 2_000_000_000,
                      "online_per_txn": 500_000_000, "per_hour": 60, "per_day": 400,
                      "kya_above": 2_000_000_000, "new_beneficiary_kya_above": 50_000_000},
    },
}

DEFAULTS = {"FX": DEFAULT_FX, "PAY": DEFAULT_PAY}
# khóa số: giá trị nhỏ hơn = chặt hơn
NUM_KEYS = {
    "FX": ["per_order_usd", "daily_usd", "max_leverage", "per_hour", "per_day", "kya_above_usd"],
    "PAY": ["transfer_per_txn", "transfer_daily", "transfer_monthly", "card_per_txn", "card_daily", "online_per_txn",
            "per_hour", "per_day", "kya_above", "new_beneficiary_kya_above"],
}
LABELS = {
    "per_order_usd": "Hạn mức / lệnh (USD)", "daily_usd": "Hạn mức / ngày (USD)", "max_leverage": "Đòn bẩy tối đa (x)",
    "per_hour": "Số lệnh / giờ", "per_day": "Số lệnh / ngày", "kya_above_usd": "Cần KYA từ (USD)",
    "transfer_per_txn": "Chuyển tiền / lần (VND)", "transfer_daily": "Chuyển tiền / ngày (VND)",
    "transfer_monthly": "Chuyển tiền / tháng (VND)", "card_per_txn": "Thẻ / giao dịch (VND)",
    "card_daily": "Thẻ / ngày (VND)", "online_per_txn": "Mua sắm online / lần (VND)",
    "kya_above": "Cần KYA từ (VND)", "new_beneficiary_kya_above": "Người nhận mới cần KYA từ (VND)",
}


def get_tsc(domain: str) -> dict:
    r = db.one("SELECT value FROM policies WHERE key=?", (f"tsc:{domain}",))
    base = copy.deepcopy(DEFAULTS[domain])
    if r:
        saved = db.jload(r["value"], {})
        base["global"].update(saved.get("global", {}))
        for seg, v in saved.get("segments", {}).items():
            base["segments"].setdefault(seg, {}).update(v)
    return base


def validate_tsc(domain: str, data: dict):
    if domain not in DEFAULTS:
        return False, "Domain không hợp lệ."
    g = data.get("global", {})
    for k in ("kya_threshold", "review_threshold", "block_threshold"):
        if k in g:
            try:
                v = float(g[k])
            except (TypeError, ValueError):
                return False, f"{k} phải là số."
            if not 0.05 <= v <= 0.99:
                return False, f"{k} phải trong 0.05–0.99."
    kt, rt, bt = (float(g.get(k, d)) for k, d in
                  (("kya_threshold", .35), ("review_threshold", .6), ("block_threshold", .8)))
    if not kt < rt < bt:
        return False, "Phải có kya_threshold < review_threshold < block_threshold."
    for seg, v in data.get("segments", {}).items():
        for k in NUM_KEYS[domain]:
            if k in v:
                try:
                    if float(v[k]) <= 0:
                        return False, f"{seg}.{k} phải > 0."
                except (TypeError, ValueError):
                    return False, f"{seg}.{k} phải là số."
    return True, "OK"


def set_tsc(domain: str, data: dict, user: str):
    ok, msg = validate_tsc(domain, data)
    if not ok:
        return False, msg
    cur = get_tsc(domain)
    cur["global"].update(data.get("global", {}))
    for seg, v in data.get("segments", {}).items():
        cur["segments"].setdefault(seg, {}).update(v)
    import time
    db.execute("INSERT INTO policies(key,value,updated_by,updated_at) VALUES(?,?,?,?) "
               "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
               (f"tsc:{domain}", db.jdump(cur), user, time.time()))
    return True, "OK"


def get_cn_limits(customer_id: str, domain: str) -> dict:
    r = db.one("SELECT value FROM limits WHERE customer_id=? AND domain=?", (customer_id, domain))
    return db.jload(r["value"], {}) if r else {}


def set_cn_limits(customer_id: str, domain: str, segment: str, values: dict, user: str):
    tsc = get_tsc(domain)["segments"].get(segment, {})
    clean = {}
    for k in NUM_KEYS[domain]:
        if k in values and values[k] not in (None, ""):
            try:
                v = float(values[k])
            except (TypeError, ValueError):
                return False, f"{k} phải là số.", None
            if v <= 0:
                return False, f"{k} phải > 0.", None
            if k in tsc and v > float(tsc[k]):
                return False, f"{LABELS.get(k, k)} = {v:,.0f} vượt trần TSC ({float(tsc[k]):,.0f}).", None
            clean[k] = v
    if "allowed_pairs" in values and domain == "FX":
        allowed = set(tsc.get("allowed_pairs", FX_PAIRS))
        pairs = [p for p in values["allowed_pairs"] if p in allowed]
        clean["allowed_pairs"] = pairs
    for hk in ("hours_from", "hours_to"):
        if hk in values and values[hk] not in (None, ""):
            clean[hk] = int(values[hk])
    import time
    db.execute("INSERT INTO limits(customer_id,domain,value,updated_by,updated_at) VALUES(?,?,?,?,?) "
               "ON CONFLICT(customer_id,domain) DO UPDATE SET value=excluded.value, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
               (customer_id, domain, db.jdump(clean), user, time.time()))
    return True, "OK", clean


def clip_agent_limits(domain: str, segment: str, customer_id: str, requested: dict):
    """Giới hạn yêu cầu của KH về ≤ trần TSC/CN (dùng khi CN duyệt)."""
    base = effective_limits(domain, segment, customer_id, None)
    out = {}
    for k in NUM_KEYS[domain]:
        if k in (requested or {}):
            try:
                out[k] = min(float(requested[k]), float(base[k]))
            except (TypeError, ValueError, KeyError):
                pass
    if domain == "FX" and "allowed_pairs" in (requested or {}):
        out["allowed_pairs"] = [p for p in requested["allowed_pairs"] if p in base.get("allowed_pairs", [])]
    for hk in ("hours_from", "hours_to"):
        if hk in (requested or {}):
            out[hk] = int(requested[hk])
    return out


def effective_limits(domain: str, segment: str, customer_id: str, agent_limits):
    """MIN(TSC phân khúc, CN theo CIF, Agent)."""
    tsc = get_tsc(domain)
    seg = tsc["segments"].get(segment) or tsc["segments"]["STANDARD"]
    eff = dict(seg)
    eff.update({"_global": tsc["global"]})
    for layer in (get_cn_limits(customer_id, domain) if customer_id else {}, agent_limits or {}):
        for k, v in layer.items():
            if k in NUM_KEYS[domain] and k in eff:
                eff[k] = min(float(eff[k]), float(v))
            elif k == "allowed_pairs" and "allowed_pairs" in eff:
                eff[k] = [p for p in eff["allowed_pairs"] if p in v]
            elif k in ("hours_from", "hours_to"):
                eff[k] = int(v)
    return eff


def kill_switch() -> dict:
    return db.meta_get("kill_switch", {"on": False, "reason": "", "by": "", "at": 0})


def set_kill_switch(on: bool, reason: str, by: str):
    import time
    db.meta_set("kill_switch", {"on": bool(on), "reason": reason, "by": by, "at": int(time.time())})
