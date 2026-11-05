"""Isolation Forest (mỗi domain một mô hình) + sinh dữ liệu huấn luyện tổng hợp bằng CHÍNH hàm feature của hệ thống."""
import os
import random
import threading
import time

import numpy as np

from agentmon import features as F
from agentmon import policy

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = {}
_lock = threading.Lock()
LAST_TRAIN = {}


def model_path(domain):
    d = os.environ.get("AGENTMON_MODEL_DIR") or os.path.join(_BASE, "models")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"iforest_{domain.lower()}.joblib")


def _persona(rng, domain):
    seg = rng.choices(["STANDARD", "VIP", "CORPORATE"], [0.5, 0.3, 0.2])[0]
    limits = dict(policy.DEFAULTS[domain]["segments"][seg])
    limits["_global"] = policy.DEFAULTS[domain]["global"]
    cap = limits["per_order_usd"] if domain == "FX" else limits["transfer_per_txn"]
    mean = cap * rng.uniform(0.04, 0.22)
    p = {"seg": seg, "limits": limits, "mean": mean, "sd": rng.uniform(0.25, 0.6),
         "h0": rng.randint(7, 11), "h1": rng.randint(16, 21),
         "pairs": rng.sample(policy.FX_PAIRS, rng.randint(2, 4)),
         "benef": [f"{rng.randint(10**9, 10**10-1)}" for _ in range(rng.randint(3, 9))],
         "merch": [f"M{rng.randint(100, 999)}" for _ in range(rng.randint(4, 12))],
         "countries": rng.choice([["VN"], ["VN", "SG"], ["VN", "US", "SG"]]),
         "lev": rng.uniform(1, 6) if domain == "FX" else 1, "balance": cap * rng.uniform(1.5, 80) * (26200 if domain == "FX" else 1)}
    return p


def _normal(rng, p, domain, ts):
    amt = max(p["mean"] * rng.lognormvariate(0, p["sd"]), 1.0)
    hr = rng.randint(p["h0"], p["h1"])
    a = {"ts": ts, "hour": hr, "channel": "AGENT"}
    if domain == "FX":
        usd = amt
        lev = max(1.0, min(p["lev"] * rng.uniform(0.6, 1.5), p["limits"]["max_leverage"]))
        a.update(domain="FX", kind="FX_TRADE", pair=rng.choice(p["pairs"]), side=rng.choice(["BUY", "SELL"]),
                 amount_usd=usd, leverage=lev, amount_vnd=usd * 26200, margin_vnd=usd * 26200 / lev)
    else:
        k = rng.choices(["TRANSFER", "ONLINE_PURCHASE", "CARD_PAYMENT"], [0.45, 0.3, 0.25])[0]
        if k != "TRANSFER":
            amt *= 0.15
        a.update(domain="PAY", kind=k, amount_vnd=float(round(amt, -3)),
                 beneficiary=rng.choice(p["benef"]) if k == "TRANSFER" else None,
                 merchant=None if k == "TRANSFER" else rng.choice(p["merch"]),
                 country=None if k == "TRANSFER" else rng.choice(p["countries"]),
                 mcc=None if k == "TRANSFER" else rng.choice(["5411", "5812", "5311", "4121", "5732"]),
                 channel_type="CNP" if k != "TRANSFER" else None, three_ds=True, margin_vnd=None)
        a["amount_vnd"] = max(a["amount_vnd"], 1000.0)
        if a["amount_vnd"] >= 1_000_000 and rng.random() < 0.35:     # con người hay trả số tiền tròn triệu
            a["amount_vnd"] = float(round(a["amount_vnd"], -6) or 1_000_000)
        if rng.random() < 0.08:      # đời thực: khách vẫn thỉnh thoảng trả cho người/merchant mới (lành tính)
            if k == "TRANSFER":
                a["beneficiary"] = str(rng.randint(10**9, 10**10 - 1))
            else:
                a["merchant"] = "MN" + str(rng.randint(1000, 9999))
    if rng.random() < 0.06:          # thỉnh thoảng giao dịch lệch giờ thường lệ (lành tính)
        a["hour"] = rng.randint(6, 23)
    return a


def _anomalous(rng, p, domain, ts):
    a = _normal(rng, p, domain, ts)
    kind = rng.choice(["big", "offhour", "bigoff", "novel", "struct", "drain"] + (["lev", "newpair"] if domain == "FX" else ["hrc", "no3ds", "newb"]))
    if kind in ("big", "bigoff"):
        m = rng.uniform(5, 14)
        if domain == "FX":
            a["amount_usd"] *= m
            a["margin_vnd"] = a["amount_usd"] * 26200 / a["leverage"]
        else:
            a["amount_vnd"] *= m
    if kind in ("offhour", "bigoff"):
        a["hour"] = rng.choice([1, 2, 3, 4])
    if kind == "drain":
        if domain == "FX":
            a["margin_vnd"] = p["balance"] * rng.uniform(0.75, 0.97)
            a["amount_usd"] = a["margin_vnd"] * a["leverage"] / 26200
        else:
            a["amount_vnd"] = p["balance"] * rng.uniform(0.75, 0.97)
    if kind == "struct":
        cap = p["limits"]["per_order_usd"] if domain == "FX" else p["limits"]["transfer_per_txn"]
        if domain == "FX":
            a["amount_usd"] = cap * rng.uniform(0.92, 0.995)
            a["margin_vnd"] = a["amount_usd"] * 26200 / a["leverage"]
        else:
            a["kind"] = "TRANSFER"
            a["amount_vnd"] = cap * rng.uniform(0.92, 0.995)
    if domain == "FX" and kind == "lev":
        a["leverage"] = p["limits"]["max_leverage"] * rng.uniform(0.9, 1.0)
        a["margin_vnd"] = a["amount_usd"] * 26200 / a["leverage"]
    if domain == "FX" and kind == "newpair":
        a["pair"] = rng.choice([x for x in policy.FX_PAIRS if x not in p["pairs"]])
        a["amount_usd"] *= rng.uniform(3, 6)
    if domain == "PAY":
        if kind == "hrc":
            a.update(kind="CARD_PAYMENT", country=rng.choice(["NG", "RU", "VE", "MM"]), mcc=rng.choice(["5967", "6540", "5816"]),
                     channel_type="CNP", beneficiary=None, merchant="MX" + str(rng.randint(1, 99)))
        if kind == "no3ds":
            a.update(kind="ONLINE_PURCHASE", channel_type="CNP", three_ds=False, merchant="MX" + str(rng.randint(1, 99)),
                     country="US", mcc="5732", beneficiary=None, amount_vnd=rng.uniform(8e6, 3e7))
        if kind == "newb":
            a.update(kind="TRANSFER", beneficiary=str(rng.randint(10**9, 10**10 - 1)), merchant=None, country=None, mcc=None,
                     channel_type=None, amount_vnd=p["mean"] * rng.uniform(4, 10))
    if kind == "novel" and domain == "PAY" and a["kind"] != "TRANSFER":
        a["country"] = "GB"
        a["merchant"] = "MN" + str(rng.randint(1, 99))
    return a


def generate(domain, n_personas=45, per=170, seed=7, anomaly_rate=0.08):
    rng = random.Random(seed)
    rows = []
    t0 = 1_700_000_000.0
    for _ in range(n_personas):
        p = _persona(rng, domain)
        hist, att = [], []
        ts = t0
        last = None
        # ~40% khách là "mới lên online": có lịch sử giao dịch tại quầy nhưng chưa từng giao dịch online/agent
        new_online = rng.random() < 0.40
        pre = rng.randint(0, 30) if new_online else 0
        grace = rng.randint(0, 2) if new_online else 0
        for j in range(pre):
            pa = _normal(rng, p, domain, t0 - (pre - j) * 86400 * rng.uniform(1, 4))
            hist.append(pa)
            last = pa["ts"]
        gap_mean = rng.uniform(0.3, 7.0) * 86400        # mỗi khách có nhịp hoạt động khác nhau (hằng ngày … hằng tuần)
        for i in range(per):
            ts += max(3600.0, rng.expovariate(1.0 / gap_mean))
            local_ok = F.local_hour(ts)
            anomalous = i > 12 and rng.random() < anomaly_rate
            if anomalous and rng.random() < 0.15:
                ts += rng.uniform(90, 220) * 86400     # tài khoản ngủ đông bỗng hoạt động
            n_burst = rng.choice([0, 0, 0, 5, 7]) if anomalous else 0
            for j in range(n_burst):     # chuỗi lệnh dồn dập
                bt = ts + j * rng.uniform(10, 40)
                b = _normal(rng, p, domain, bt)
                if domain == "PAY":
                    b.update(kind="CARD_PAYMENT", amount_vnd=float(rng.choice([2000, 5000, 10000])), country="US",
                             merchant="MT" + str(j), mcc="5732", channel_type="CNP", three_ds=False, beneficiary=None)
                ctx = F.Ctx(domain, bt, hist[-150:], [x for x in att if bt - x["ts"] < 86400], p["balance"], p["limits"],
                            set(), online_exec_any=max(0, len(hist) - pre - grace), last_exec_ts=last, agent_prior=i)
                rows.append((F.feature_vector(b, ctx), 1))
                att.append({"ts": bt, "amount_vnd": b.get("amount_vnd"), "decision": "ALLOW"})
            a = _anomalous(rng, p, domain, ts) if anomalous else _normal(rng, p, domain, ts)
            a["ts"] = ts
            if not anomalous:
                a["hour"] = F.local_hour(ts) if rng.random() < 0.15 else a["hour"]
            ctx = F.Ctx(domain, ts, hist[-150:], [x for x in att if ts - x["ts"] < 86400], p["balance"], p["limits"],
                        set(), online_exec_any=max(0, len(hist) - pre - grace), last_exec_ts=last, agent_prior=i)
            ctx.cum = {"day": 0.0}
            rows.append((F.feature_vector(a, ctx), 1 if anomalous else 0))
            att.append({"ts": ts, "amount_vnd": a.get("amount_vnd"), "decision": "ALLOW"})
            if not anomalous:
                hist.append(a)
                last = ts
    return rows


def train(domain, n_personas=45, per=170, seed=7):
    from sklearn.ensemble import IsolationForest
    import joblib
    t = time.time()
    rows = generate(domain, n_personas, per, seed)
    cols = F.COLS[domain]
    X = np.array([[r[0][c] for c in cols] for r in rows])
    y = np.array([r[1] for r in rows])
    model = IsolationForest(n_estimators=250, contamination=0.08, random_state=seed, n_jobs=1, max_samples=0.8)
    model.fit(X)
    raw = -model.score_samples(X)
    p50, p995 = float(np.percentile(raw, 50)), float(np.percentile(raw, 99.5))
    pred = model.predict(X) == -1
    tp = int(((pred) & (y == 1)).sum())
    info = {"domain": domain, "trained_at": int(time.time()), "n_samples": int(len(X)), "n_anomaly_injected": int(y.sum()),
            "detected_injected_pct": round(100 * tp / max(int(y.sum()), 1), 1),
            "flagged_normal_pct": round(100 * int((pred & (y == 0)).sum()) / max(int((y == 0).sum()), 1), 1),
            "features": cols, "p50": p50, "p995": p995, "seconds": round(time.time() - t, 1)}
    joblib.dump({"model": model, "cols": cols, "p50": p50, "p995": p995, "info": info}, model_path(domain))
    with _lock:
        _cache.pop(domain, None)
    LAST_TRAIN[domain] = info
    return info


def _load(domain):
    import joblib
    path = model_path(domain)
    with _lock:
        mt = os.path.getmtime(path) if os.path.exists(path) else None
        c = _cache.get(domain)
        if c and c[0] == mt and mt is not None:
            return c[1]
        obj = None
        if mt is not None:
            try:
                obj = joblib.load(path)
            except Exception:
                obj = None
    if obj is None:
        train(domain)
        obj = joblib.load(path)
        mt = os.path.getmtime(path)
    with _lock:
        _cache[domain] = (mt, obj)
    return obj


def status():
    out = {}
    for d in ("FX", "PAY"):
        try:
            out[d] = _load(d)["info"]
        except Exception as e:      # noqa: BLE001
            out[d] = {"error": str(e)[:100]}
    return out


def anomaly(domain, vec: dict) -> float:
    m = _load(domain)
    x = np.array([[vec[c] for c in m["cols"]]])
    raw = float(-m["model"].score_samples(x)[0])
    span = max(m["p995"] - m["p50"], 1e-6)
    return float(min(max((raw - m["p50"]) / span, 0.0), 1.0))
