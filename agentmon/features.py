"""
Feature engineering + điểm hành vi + điểm velocity (anti-bot) + trigger KYA.
Dùng CHUNG cho: (a) chấm điểm thời gian thực từ DB, (b) sinh dữ liệu huấn luyện Isolation Forest.
Mọi hàm nhận `Ctx` (không đụng DB) nên test và huấn luyện độc lập.
"""
import math
from collections import Counter

LOCAL_TZ_OFFSET = 7 * 3600     # Asia/Ho_Chi_Minh


def local_hour(ts: float) -> int:
    return int(((ts + LOCAL_TZ_OFFSET) // 3600) % 24)


class Ctx:
    def __init__(self, domain, now, hist=None, attempts=None, balance=0.0, limits=None, trusted=None,
                 online_exec_any=0, last_exec_ts=None, agent_prior=0, probation_left=0, suspicion=0.0,
                 watchlist=False, cum=None, thin_override=None):
        self.domain = domain
        self.now = now
        self.hist = hist or []              # giao dịch ĐÃ THỰC HIỆN cùng domain (baseline hành vi)
        self.attempts = attempts or []      # mọi lần agent gửi (mọi trạng thái) 24h gần nhất
        self.balance = balance              # số dư khả dụng (đã trừ phần đang chờ)
        self.limits = limits or {}
        self.trusted = trusted or set()
        self.online_exec_any = online_exec_any
        self.last_exec_ts = last_exec_ts
        self.agent_prior = agent_prior
        self.probation_left = probation_left
        self.suspicion = suspicion
        self.watchlist = watchlist
        self.cum = cum or {}


def amt_of(a: dict, domain: str) -> float:
    return float(a.get("amount_usd") or 0) if domain == "FX" else float(a.get("amount_vnd") or 0)


def _stats(ctx: Ctx, kind=None):
    base = ctx.hist
    if ctx.domain == "PAY" and kind:
        same = [h for h in ctx.hist if h.get("kind") == kind]
        if len(same) >= 5:
            base = same             # baseline số tiền theo TỪNG loại (chuyển khoản ≠ thẻ)
    vals = [amt_of(h, ctx.domain) for h in base]
    vals = [v for v in vals if v > 0]
    n = len(vals)
    if n:
        mean = sum(vals) / n
        std = math.sqrt(sum((v - mean) ** 2 for v in vals) / n)
    else:
        mean = std = 0.0
    hours = Counter(local_hour(h["ts"]) for h in ctx.hist)
    typical = {h for h, c in hours.items() if c >= max(2, 0.04 * n)}
    levs = [float(h.get("leverage") or 1) for h in ctx.hist if h.get("leverage")]
    return {
        "n": len(ctx.hist), "n_kind": n, "mean": mean, "std": std, "typical_hours": typical,
        "pairs": {h.get("pair") for h in ctx.hist if h.get("pair")},
        "benef": Counter(h.get("beneficiary") for h in ctx.hist if h.get("beneficiary")),
        "merch": {h.get("merchant") for h in ctx.hist if h.get("merchant")},
        "countries": {h.get("country") for h in ctx.hist if h.get("country")},
        "lev_mean": (sum(levs) / len(levs)) if levs else 1.0,
    }


def _cap(ctx: Ctx, a: dict) -> float:
    L = ctx.limits
    if ctx.domain == "FX":
        return float(L.get("per_order_usd") or 1)
    k = a.get("kind")
    key = {"TRANSFER": "transfer_per_txn", "CARD_PAYMENT": "card_per_txn", "ONLINE_PURCHASE": "online_per_txn"}.get(k, "transfer_per_txn")
    return float(L.get(key) or 1)


def context_flags(a: dict, ctx: Ctx):
    """Các đại lượng trung gian dùng chung."""
    st = _stats(ctx, a.get("kind"))
    amt = amt_of(a, ctx.domain)
    thin = st["n_kind"] < 5
    mean = st["mean"] if not thin else max(_cap(ctx, a) * 0.1, 1.0)
    std = st["std"] if not thin else mean * 0.5
    ratio = min(amt / (mean + 1e-9), 30.0)
    z = max(-3.0, min((amt - mean) / (std + 0.25 * mean + 1e-9), 12.0))
    now = ctx.now
    n5 = sum(1 for x in ctx.attempts if now - x["ts"] <= 300) + 1
    n1h = sum(1 for x in ctx.attempts if now - x["ts"] <= 3600) + 1
    n24 = len(ctx.attempts) + 1
    gaps = sorted(x["ts"] for x in ctx.attempts if now - x["ts"] <= 3600)
    cv = 1.0
    if len(gaps) >= 8:
        d = [b - a_ for a_, b in zip(gaps, gaps[1:])]
        m = sum(d) / len(d)
        if m > 0:
            cv = math.sqrt(sum((x - m) ** 2 for x in d) / len(d)) / m
    small_burst = sum(1 for x in ctx.attempts if now - x["ts"] <= 600 and (x.get("amount_vnd") or 0) < 50_000) + \
        (1 if (a.get("amount_vnd") or 0) < 50_000 and ctx.domain == "PAY" else 0)
    decl24 = sum(1 for x in ctx.attempts if x.get("decision") in ("BLOCK",))
    dormant_days = max(0.0, (now - ctx.last_exec_ts) / 86400.0) if ctx.last_exec_ts else 365.0
    hr = a.get("hour")
    if hr is None:
        hr = local_hour(now)
    g = ctx.limits.get("_global", {})
    need_vnd = a.get("margin_vnd") if ctx.domain == "FX" else a.get("amount_vnd")
    bal_pct = (float(need_vnd or 0) / ctx.balance) if ctx.balance > 0 else 5.0
    return dict(st=st, amt=amt, thin=thin, mean=mean, ratio=ratio, z=z, n5=n5, n1h=n1h, n24=n24, cv=cv,
                small_burst=small_burst, decl24=decl24, dormant_days=min(dormant_days, 365.0), hour=hr,
                bal_pct=min(bal_pct, 5.0), g=g, first_online=ctx.online_exec_any == 0,
                atypical_hour=(not thin and st["n"] >= 8 and hr not in st["typical_hours"]),
                off_hour=hr in (0, 1, 2, 3, 4, 5, 23))


FX_COLS = ["amt_log", "z", "ratio", "hour_sin", "hour_cos", "off_hour", "atypical_hour", "n5", "n1h", "n24",
           "cv_reg", "pct_limit", "bal_pct", "dormant", "first_online", "thin", "lev", "lev_ratio", "pair_new",
           "daily_pct", "susp"]
PAY_COLS = ["amt_log", "z", "ratio", "hour_sin", "hour_cos", "off_hour", "atypical_hour", "n5", "n1h", "n24",
            "cv_reg", "pct_limit", "bal_pct", "dormant", "first_online", "thin", "is_transfer", "is_online", "is_card",
            "new_benef", "benef_cnt", "new_merchant", "new_country", "hr_country", "hr_mcc", "no3ds", "small_burst",
            "structuring", "round", "decl24", "susp"]
COLS = {"FX": FX_COLS, "PAY": PAY_COLS}


def feature_vector(a: dict, ctx: Ctx) -> dict:
    f = context_flags(a, ctx)
    st = f["st"]
    g = f["g"]
    hr = f["hour"]
    v = {
        "amt_log": math.log1p(f["amt"]), "z": f["z"], "ratio": f["ratio"],
        "hour_sin": math.sin(2 * math.pi * hr / 24), "hour_cos": math.cos(2 * math.pi * hr / 24),
        "off_hour": float(f["off_hour"]), "atypical_hour": float(f["atypical_hour"]),
        "n5": float(f["n5"]), "n1h": float(f["n1h"]), "n24": float(f["n24"]),
        "cv_reg": max(0.0, 1.0 - f["cv"]) if f["n1h"] >= 8 else 0.0,
        "pct_limit": min(f["amt"] / _cap(ctx, a), 3.0), "bal_pct": f["bal_pct"],
        "dormant": f["dormant_days"] / 365.0, "first_online": float(f["first_online"]), "thin": float(f["thin"]),
        "susp": float(ctx.suspicion),
    }
    if ctx.domain == "FX":
        lev = float(a.get("leverage") or 1)
        v.update({
            "lev": lev, "lev_ratio": min(lev / (st["lev_mean"] + 1e-9), 20.0),
            "pair_new": float(bool(a.get("pair")) and a["pair"] not in st["pairs"] and st["n"] >= 5),
            "daily_pct": min((ctx.cum.get("day", 0.0) + f["amt"]) / float(ctx.limits.get("daily_usd") or 1), 3.0),
        })
    else:
        k = a.get("kind")
        ben = a.get("beneficiary")
        new_b = bool(k == "TRANSFER" and ben and ben not in st["benef"] and ben not in ctx.trusted)
        mer = a.get("merchant")
        ctry = a.get("country")
        v.update({
            "is_transfer": float(k == "TRANSFER"), "is_online": float(k == "ONLINE_PURCHASE"),
            "is_card": float(k == "CARD_PAYMENT"),
            "new_benef": float(new_b), "benef_cnt": math.log1p(st["benef"].get(ben, 0)) if ben else 0.0,
            "new_merchant": float(bool(mer) and mer not in st["merch"] and st["n"] >= 5),
            "new_country": float(bool(ctry) and ctry not in st["countries"] and st["n"] >= 5 and k != "TRANSFER"),
            "hr_country": float(ctry in g.get("high_risk_countries", [])),
            "hr_mcc": float(a.get("mcc") in g.get("high_risk_mcc", [])),
            "no3ds": float(k in ("ONLINE_PURCHASE", "CARD_PAYMENT") and a.get("channel_type") == "CNP"
                           and not a.get("three_ds") and f["amt"] >= g.get("cnp_3ds_above_vnd", 5_000_000)),
            "small_burst": float(f["small_burst"]),
            "structuring": float(0.90 <= f["amt"] / _cap(ctx, a) < 1.0),
            "round": float(f["amt"] >= 1_000_000 and f["amt"] % 1_000_000 == 0),
            "decl24": float(f["decl24"]),
        })
    return {c: float(v.get(c, 0.0)) for c in COLS[ctx.domain]}


def behavior_score(a: dict, ctx: Ctx):
    f = context_flags(a, ctx)
    st = f["st"]
    g = f["g"]
    s = 0.0
    why = []

    def add(x, msg):
        nonlocal s
        s += x
        why.append(msg)

    unit = "USD" if ctx.domain == "FX" else "VND"
    if f["ratio"] >= 6:
        add(0.50, f"Giá trị gấp {f['ratio']:.1f} lần mức trung bình của chính khách hàng")
    elif f["ratio"] >= 3:
        add(0.35, f"Giá trị gấp {f['ratio']:.1f} lần mức trung bình của chính khách hàng")
    elif f["ratio"] >= 2:
        add(0.12, f"Giá trị gấp {f['ratio']:.1f} lần mức trung bình")
    if f["z"] >= 3:
        add(0.10, "Lệch chuẩn thống kê lớn so với lịch sử")
    if f["atypical_hour"]:
        add(0.15, f"Giờ giao dịch ({f['hour']}h) khác thói quen")
    if f["first_online"]:
        add(0.25, "Khách hàng chưa từng giao dịch online/agent trước đây")
    if f["dormant_days"] >= g.get("dormant_days", 60) and ctx.last_exec_ts:
        add(0.25, f"Tài khoản không hoạt động {int(f['dormant_days'])} ngày, nay giao dịch lại")
    if f["bal_pct"] >= g.get("balance_drain_pct", 0.7):
        add(0.25, f"Giao dịch dùng {min(f['bal_pct'],1)*100:.0f}% số dư khả dụng")
    if f["thin"] and not f["first_online"]:
        add(0.10, "Lịch sử hành vi mỏng (< 5 giao dịch)")
    if ctx.domain == "FX":
        lev = float(a.get("leverage") or 1)
        if lev > 10 and lev > st["lev_mean"] * 2.5:
            add(0.25, f"Đòn bẩy {lev:g}x cao hơn nhiều thói quen ({st['lev_mean']:.1f}x)")
        if a.get("pair") and a["pair"] not in st["pairs"] and st["n"] >= 5:
            add(0.15, f"Cặp {a['pair']} chưa từng giao dịch")
    else:
        k = a.get("kind")
        if k == "TRANSFER" and a.get("beneficiary") and a["beneficiary"] not in st["benef"] \
                and a["beneficiary"] not in ctx.trusted:
            add(0.25, "Người thụ hưởng mới (chưa từng chuyển tiền)")
        if k in ("ONLINE_PURCHASE", "CARD_PAYMENT"):
            if a.get("merchant") and a["merchant"] not in st["merch"] and st["n"] >= 5:
                add(0.10, "Merchant mới")
            if a.get("country") and a["country"] not in st["countries"] and st["n"] >= 5:
                add(0.25, f"Quốc gia {a['country']} chưa từng phát sinh giao dịch")
            if a.get("country") in g.get("high_risk_countries", []):
                add(0.20, f"Quốc gia rủi ro cao ({a['country']})")
            if a.get("mcc") in g.get("high_risk_mcc", []):
                add(0.15, f"Ngành hàng rủi ro cao (MCC {a['mcc']})")
    return min(s, 1.0), why


def velocity_score(a: dict, ctx: Ctx):
    f = context_flags(a, ctx)
    s = 0.0
    why = []
    ph = float(ctx.limits.get("per_hour") or 30)

    def add(x, msg):
        nonlocal s
        s += x
        why.append(msg)

    if f["n1h"] >= 0.8 * ph:
        add(0.35, f"{f['n1h']} giao dịch/giờ sát trần {ph:g}")
    elif f["n1h"] >= 0.5 * ph:
        add(0.15, f"{f['n1h']} giao dịch/giờ (≥50% trần)")
    if f["n5"] >= 5:
        add(0.30, f"{f['n5']} giao dịch trong 5 phút")
    elif f["n5"] >= 3:
        add(0.10, f"{f['n5']} giao dịch trong 5 phút")
    if ctx.domain == "PAY":
        if f["small_burst"] >= 5:
            add(0.45, f"{f['small_burst']} giao dịch giá trị rất nhỏ trong 10 phút (dấu hiệu dò thẻ / card testing)")
        cap = _cap(ctx, a)
        if 0.90 <= f["amt"] / cap < 1.0:
            add(0.25, "Số tiền sát trần hạn mức (nghi tách nhỏ/né hạn mức)")
    if f["decl24"] >= 3:
        add(0.25, f"{f['decl24']} lần bị chặn trong 24h gần đây")
    if f["n1h"] >= 8 and f["cv"] < 0.1:
        add(0.20, "Nhịp gửi lệnh đều bất thường (kịch bản tự động)")
    if f["off_hour"] and f["ratio"] > 3:
        add(0.20, "Giao dịch lớn ngoài giờ")
    return min(s, 1.0), why


def triggers(a: dict, ctx: Ctx):
    """Điều kiện BẮT BUỘC xác minh KYA (xác định, không phụ thuộc ML)."""
    f = context_flags(a, ctx)
    g = f["g"]
    L = ctx.limits
    T = []
    amt = f["amt"]
    if ctx.domain == "FX":
        if amt >= float(L.get("kya_above_usd") or 1e18):
            T.append(("AMOUNT_OVER_KYA", f"Giá trị {amt:,.0f} USD ≥ ngưỡng bắt buộc xác minh"))
        lev = float(a.get("leverage") or 1)
        if lev > 10 and lev > f["st"]["lev_mean"] * 2.5 and f["st"]["n"] >= 5:
            T.append(("LEVERAGE_SPIKE", f"Đòn bẩy {lev:g}x tăng đột biến so với thói quen"))
    else:
        if amt >= float(L.get("kya_above") or 1e18):
            T.append(("AMOUNT_OVER_KYA", f"Giá trị {amt:,.0f} VND ≥ ngưỡng bắt buộc xác minh"))
        if a.get("kind") == "TRANSFER" and a.get("beneficiary") and a["beneficiary"] not in f["st"]["benef"] \
                and a["beneficiary"] not in ctx.trusted and amt >= float(L.get("new_beneficiary_kya_above") or 0):
            T.append(("NEW_BENEFICIARY", "Chuyển cho người nhận mới vượt ngưỡng"))
        if a.get("kind") in ("ONLINE_PURCHASE", "CARD_PAYMENT"):
            if a.get("channel_type") == "CNP" and not a.get("three_ds") and amt >= g.get("cnp_3ds_above_vnd", 5_000_000):
                T.append(("NO_3DS", "Giao dịch thẻ không có 3-D Secure vượt ngưỡng"))
            if a.get("country") in g.get("high_risk_countries", []):
                T.append(("HIGH_RISK_COUNTRY", f"Quốc gia rủi ro cao ({a['country']})"))
            elif a.get("country") and a["country"] not in f["st"]["countries"] and f["st"]["n"] >= 5 and a.get("country") != "VN":
                T.append(("NEW_COUNTRY", f"Quốc gia mới ({a['country']})"))
            if a.get("mcc") in g.get("high_risk_mcc", []):
                T.append(("HIGH_RISK_MCC", f"Ngành hàng rủi ro cao (MCC {a['mcc']})"))
    if f["first_online"]:
        T.append(("FIRST_ONLINE", "Khách hàng chưa từng giao dịch online/agent – nay phát sinh lần đầu"))
    if ctx.last_exec_ts and f["dormant_days"] >= g.get("dormant_days", 60):
        T.append(("DORMANT_WAKE", f"Tài khoản ngủ đông {int(f['dormant_days'])} ngày nay giao dịch"))
    if f["bal_pct"] >= g.get("balance_drain_pct", 0.7) and f["bal_pct"] < 1.0:
        T.append(("BALANCE_DRAIN", f"Giao dịch dùng {f['bal_pct']*100:.0f}% số dư khả dụng"))
    if ctx.probation_left > 0:
        T.append(("AGENT_PROBATION", f"Agent mới đăng ký – còn {ctx.probation_left} giao dịch thử việc"))
    if f["small_burst"] >= 5 and ctx.domain == "PAY":
        T.append(("CARD_TESTING", "Chuỗi giao dịch nhỏ liên tiếp nghi dò thẻ"))
    return T
