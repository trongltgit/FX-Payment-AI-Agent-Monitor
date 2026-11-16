"""Isolation Forest (mỗi domain một mô hình) + sinh dữ liệu huấn luyện tổng hợp bằng CHÍNH hàm feature của hệ thống.

Phiên bản hóa mô hình (v1.1):
  * Mỗi lần huấn luyện tạo `version` = <domain>-<ngày>-<băm8(cột đặc trưng + tham số + dữ liệu)>.
  * models/MANIFEST.json lưu lịch sử: version, SHA-256 file, số mẫu, nguồn dữ liệu, chỉ số in-sample và HOLDOUT.
  * Quyết định của engine ghi version + SHA-256 mô hình đã dùng (xem engine trace) → tái lập/kiểm toán được.
  * AGENTMON_MODEL_ARCHIVE=1 lưu thêm bản sao models/archive/<version>.joblib để nạp lại đúng mô hình cũ.
"""
import hashlib
import json
import os
import random
import shutil
import threading
import time

import numpy as np

from agentmon import features as F
from agentmon import policy
from agentmon.constants import CODE_VERSION

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cache = {}
_lock = threading.Lock()
LAST_TRAIN = {}
PARAMS = {"n_estimators": 150, "contamination": 0.08, "max_samples": 256}
POLICY_THRESHOLDS = (0.35, 0.65, 0.85)     # KYA / REVIEW / BLOCK mặc định – dùng khi đánh giá
PAY_KIND_W = [("TRANSFER", .35), ("ONLINE_PURCHASE", .20), ("CARD_PAYMENT", .15), ("ATM_WITHDRAWAL", .07),
              ("WALLET_PAYMENT", .08), ("BILL_PAYMENT", .08), ("QR_PAYMENT", .07)]


def model_dir():
    d = os.environ.get("AGENTMON_MODEL_DIR") or os.path.join(_BASE, "models")
    os.makedirs(d, exist_ok=True)
    return d


def model_path(domain):
    return os.path.join(model_dir(), f"iforest_{domain.lower()}.joblib")


def manifest_path():
    return os.path.join(model_dir(), "MANIFEST.json")


def read_manifest():
    try:
        with open(manifest_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_add(domain, entry):
    m = read_manifest()
    d = m.setdefault(domain, {"current": None, "history": []})
    d["history"] = (d.get("history") or [])[-19:] + [entry]
    d["current"] = entry["version"]
    tmp = manifest_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(m, fh, ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, manifest_path())


# --------------------------------------------------------------------------- dữ liệu tổng hợp
def _persona(rng, domain):
    seg = rng.choices(["STANDARD", "VIP", "CORPORATE"], [0.5, 0.3, 0.2])[0]
    limits = dict(policy.DEFAULTS[domain]["segments"][seg])
    limits["_global"] = policy.DEFAULTS[domain]["global"]
    cap = limits["per_order_usd"] if domain == "FX" else limits["transfer_per_txn"]
    mean = cap * rng.uniform(0.04, 0.22)
    return {"seg": seg, "limits": limits, "mean": mean, "sd": rng.uniform(0.25, 0.6),
            "h0": rng.randint(7, 11), "h1": rng.randint(16, 21),
            "pairs": rng.sample(policy.FX_PAIRS, rng.randint(2, 4)),
            "benef": [f"{rng.randint(10**9, 10**10-1)}" for _ in range(rng.randint(3, 9))],
            "merch": [f"M{rng.randint(100, 999)}" for _ in range(rng.randint(4, 12))],
            "countries": rng.choice([["VN"], ["VN", "SG"], ["VN", "US", "SG"]]),
            "lev": rng.uniform(1, 6) if domain == "FX" else 1,
            "balance": cap * rng.uniform(1.5, 80) * (26200 if domain == "FX" else 1),
            # kênh thẻ/số: không phải khách nào cũng dùng
            "atm_user": rng.random() < 0.6, "wallet_user": rng.random() < 0.55, "digital_user": rng.random() < 0.6,
            "atms": [f"ATM{rng.randint(1000, 9999)}" for _ in range(rng.randint(2, 4))],
            "devices": [f"DEV-{rng.randint(10**5, 10**6 - 1)}" for _ in range(rng.randint(1, 2))],
            "billers": [f"BILL{rng.randint(10, 99)}" for _ in range(rng.randint(2, 5))],
            "dchan": rng.choice(["DIGIBANK", "DIGIBANK", "DIGIBIZ"] if seg != "CORPORATE" else ["DIGIBIZ"])}


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
        k = rng.choices([x[0] for x in PAY_KIND_W], [x[1] for x in PAY_KIND_W])[0]
        if k == "ATM_WITHDRAWAL" and not p["atm_user"]:
            k = "CARD_PAYMENT"
        if k == "WALLET_PAYMENT" and not p["wallet_user"]:
            k = "ONLINE_PURCHASE"
        if k in ("BILL_PAYMENT", "QR_PAYMENT") and not p["digital_user"]:
            k = "TRANSFER"
        if k != "TRANSFER":
            amt *= 0.15
        mcc_pool = ["5411", "5812", "5311", "4121", "5732"]
        a.update(domain="PAY", kind=k, amount_vnd=float(round(amt, -3)), beneficiary=None, merchant=None, country=None,
                 mcc=None, channel_type=None, three_ds=True, margin_vnd=None, device_id=None)
        if k == "TRANSFER":
            a["beneficiary"] = rng.choice(p["benef"])
        elif k == "ONLINE_PURCHASE":
            a.update(merchant=rng.choice(p["merch"]), country=rng.choice(p["countries"]), mcc=rng.choice(mcc_pool), channel_type="CNP")
        elif k == "CARD_PAYMENT":
            a.update(merchant=rng.choice(p["merch"]), country=rng.choice(p["countries"]), mcc=rng.choice(mcc_pool), channel_type="POS")
        elif k == "ATM_WITHDRAWAL":
            a.update(merchant=rng.choice(p["atms"]), country="VN" if rng.random() < 0.97 else rng.choice(p["countries"]), mcc="6011",
                     channel_type="ATM", amount_vnd=float(max(500_000, min(round(amt * 3, -5), 10_000_000))))
        elif k == "WALLET_PAYMENT":
            a.update(merchant=rng.choice(p["merch"]), country=rng.choice(p["countries"]), mcc=rng.choice(mcc_pool), channel_type="WALLET",
                     device_id=rng.choice(p["devices"]))
        else:   # BILL_PAYMENT / QR_PAYMENT trên Digibank/Digibiz
            a.update(merchant=rng.choice(p["billers"] if k == "BILL_PAYMENT" else p["merch"]), country="VN",
                     mcc="4900" if k == "BILL_PAYMENT" else rng.choice(mcc_pool), channel_type=p["dchan"])
        a["amount_vnd"] = max(a["amount_vnd"], 1000.0)
        if a["amount_vnd"] >= 1_000_000 and k != "ATM_WITHDRAWAL" and rng.random() < 0.35:     # người hay trả số tiền tròn triệu
            a["amount_vnd"] = float(round(a["amount_vnd"], -6) or 1_000_000)
        if rng.random() < 0.08 and k != "ATM_WITHDRAWAL":      # đời thực: thỉnh thoảng trả cho người/merchant mới (lành tính)
            if k == "TRANSFER":
                a["beneficiary"] = str(rng.randint(10**9, 10**10 - 1))
            else:
                a["merchant"] = "MN" + str(rng.randint(1000, 9999))
    # Người thực hiện: ~70% giao dịch của NGƯỜI (điểm bot phiên thấp, có thiết bị), ~30% của Agent
    human = rng.random() < 0.70
    a["actor_type"] = "HUMAN" if human else "AGENT"
    a["session_risk"] = rng.uniform(0.0, 0.25) if human else 0.0
    if human:
        a["device_id"] = rng.choice(p["devices"]) if rng.random() > 0.03 else "DEV-NEW" + str(rng.randint(10**4, 10**5))   # 3% đổi máy hợp lệ
    a["_cross"] = 1 if rng.random() < 0.05 else 0
    a["_senders"] = 1 if (domain == "PAY" and a.get("kind") == "TRANSFER" and rng.random() < 0.04) else 0
    if rng.random() < 0.06:          # thỉnh thoảng giao dịch lệch giờ thường lệ (lành tính)
        a["hour"] = rng.randint(6, 23)
    return a


def _anomalous(rng, p, domain, ts):
    a = _normal(rng, p, domain, ts)
    kind = rng.choice(["big", "offhour", "bigoff", "novel", "struct", "drain"]
                      + ["botsess", "actorconf"]
                      + (["lev", "newpair"] if domain == "FX" else ["hrc", "no3ds", "newb", "newdev", "atmabroad", "mule", "newdevx"]))
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
            a.update(kind="TRANSFER", amount_vnd=cap * rng.uniform(0.92, 0.995), channel_type=None, device_id=None)
    if domain == "FX" and kind == "lev":
        a["leverage"] = p["limits"]["max_leverage"] * rng.uniform(0.9, 1.0)
        a["margin_vnd"] = a["amount_usd"] * 26200 / a["leverage"]
    if domain == "FX" and kind == "newpair":
        a["pair"] = rng.choice([x for x in policy.FX_PAIRS if x not in p["pairs"]])
        a["amount_usd"] *= rng.uniform(3, 6)
    if domain == "PAY":
        if kind == "hrc":
            a.update(kind="CARD_PAYMENT", country=rng.choice(["NG", "RU", "VE", "MM"]), mcc=rng.choice(["5967", "6540", "5816"]),
                     channel_type="CNP", beneficiary=None, merchant="MX" + str(rng.randint(1, 99)), device_id=None)
        if kind == "no3ds":
            a.update(kind="ONLINE_PURCHASE", channel_type="CNP", three_ds=False, merchant="MX" + str(rng.randint(1, 99)),
                     country="US", mcc="5732", beneficiary=None, amount_vnd=rng.uniform(8e6, 3e7), device_id=None)
        if kind == "newb":
            a.update(kind="TRANSFER", beneficiary=str(rng.randint(10**9, 10**10 - 1)), merchant=None, country=None, mcc=None,
                     channel_type=None, device_id=None, amount_vnd=p["mean"] * rng.uniform(4, 10))
        if kind == "newdev":
            a.update(kind="WALLET_PAYMENT", channel_type="WALLET", device_id="DEV-N" + str(rng.randint(10**5, 10**6)),
                     merchant="MX" + str(rng.randint(1, 99)), mcc=rng.choice(["5732", "5311", "5944"]), country="VN",
                     beneficiary=None, amount_vnd=p["mean"] * rng.uniform(3, 8))
        if kind == "atmabroad":
            a.update(kind="ATM_WITHDRAWAL", channel_type="ATM", merchant="ATMX" + str(rng.randint(1, 99)), mcc="6011",
                     country=rng.choice(["TH", "US", "GB", "CN"]), beneficiary=None, device_id=None,
                     amount_vnd=rng.uniform(5e6, 1e7), hour=rng.choice([1, 2, 3, 4]), three_ds=False)
    if kind == "botsess":
        a["actor_type"], a["session_risk"] = "HUMAN", rng.uniform(0.75, 1.0)
        if domain == "FX":
            a["amount_usd"] *= rng.uniform(3, 8)
            a["margin_vnd"] = a["amount_usd"] * 26200 / a["leverage"]
        else:
            a["amount_vnd"] *= rng.uniform(3, 8)
    if kind == "actorconf":
        a["_cross"] = rng.randint(4, 8)
    if domain == "PAY" and kind == "mule":
        a.update(kind="TRANSFER", beneficiary=str(rng.randint(10**9, 10**10 - 1)), merchant=None, country=None, mcc=None, channel_type=None,
                 amount_vnd=p["mean"] * rng.uniform(2, 6), actor_type="HUMAN")
        a["_senders"] = rng.randint(3, 9)
    if domain == "PAY" and kind == "newdevx":
        a.update(kind="TRANSFER", beneficiary=str(rng.randint(10**9, 10**10 - 1)), merchant=None, country=None, mcc=None, channel_type=None,
                 amount_vnd=p["mean"] * rng.uniform(3, 8), actor_type="HUMAN", device_id="DEV-N" + str(rng.randint(10**5, 10**6)))
        a["session_risk"] = rng.uniform(0.0, 0.3)
    if kind == "novel" and domain == "PAY" and a["kind"] not in ("TRANSFER", "ATM_WITHDRAWAL"):
        a["country"] = "GB"
        a["merchant"] = "MN" + str(rng.randint(1, 99))
    return a


def _row(a, ctx, label, with_scores):
    vec = F.feature_vector(a, ctx)
    if not with_scores:
        return (vec, label)
    beh, _ = F.behavior_score(a, ctx)
    vel, _ = F.velocity_score(a, ctx)
    return (vec, label, beh, vel, tuple(sorted(t[0] for t in F.triggers(a, ctx))))


def generate(domain, n_personas=45, per=170, seed=7, anomaly_rate=0.08, with_scores=False):
    """Sinh dữ liệu tổng hợp. with_scores=True trả thêm điểm hành vi/velocity để đánh giá quyết định cuối (holdout)."""
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
            anomalous = i > 12 and rng.random() < anomaly_rate
            if anomalous and rng.random() < 0.15:
                ts += rng.uniform(90, 220) * 86400     # tài khoản ngủ đông bỗng hoạt động
            n_burst = rng.choice([0, 0, 0, 5, 7]) if anomalous else 0
            for j in range(n_burst):     # chuỗi lệnh dồn dập
                bt = ts + j * rng.uniform(10, 40)
                b = _normal(rng, p, domain, bt)
                if domain == "PAY":
                    b.update(kind="CARD_PAYMENT", amount_vnd=float(rng.choice([2000, 5000, 10000])), country="US",
                             merchant="MT" + str(j), mcc="5732", channel_type="CNP", three_ds=False, beneficiary=None, device_id=None)
                ctx = F.Ctx(domain, bt, hist[-150:], [x for x in att if bt - x["ts"] < 86400], p["balance"], p["limits"],
                            set(), online_exec_any=max(0, len(hist) - pre - grace), last_exec_ts=last, agent_prior=i)
                ctx.actor, ctx.cross_actor_n10, ctx.benef_senders = b.get("actor_type", "AGENT"), b.pop("_cross", 0), b.pop("_senders", 0)
                rows.append(_row(b, ctx, 1, with_scores))
                att.append({"ts": bt, "amount_vnd": b.get("amount_vnd"), "decision": "ALLOW", "merchant": b.get("merchant")})
            a = _anomalous(rng, p, domain, ts) if anomalous else _normal(rng, p, domain, ts)
            a["ts"] = ts
            if not anomalous:
                a["hour"] = F.local_hour(ts) if rng.random() < 0.15 else a["hour"]
            ctx = F.Ctx(domain, ts, hist[-150:], [x for x in att if ts - x["ts"] < 86400], p["balance"], p["limits"],
                        set(), online_exec_any=max(0, len(hist) - pre - grace), last_exec_ts=last, agent_prior=i)
            ctx.cum = {"day": 0.0}
            ctx.actor, ctx.cross_actor_n10, ctx.benef_senders = a.get("actor_type", "AGENT"), a.pop("_cross", 0), a.pop("_senders", 0)
            rows.append(_row(a, ctx, 1 if anomalous else 0, with_scores))
            att.append({"ts": ts, "amount_vnd": a.get("amount_vnd"), "decision": "ALLOW", "merchant": a.get("merchant")})
            if not anomalous:
                hist.append(a)
                last = ts
    return rows


# --------------------------------------------------------------------------- huấn luyện / đánh giá
def _norm_scores(pkg, X):
    raw = -pkg["model"].score_samples(X)
    span = max(pkg["p995"] - pkg["p50"], 1e-6)
    return np.clip((raw - pkg["p50"]) / span, 0.0, 1.0)


def evaluate_rows(pkg, rows, thresholds=POLICY_THRESHOLDS):
    """Đánh giá trên tập (vec,label,beh,vel,trigger). Không dùng dữ liệu huấn luyện.
    Trả: AUC/AP của điểm ML; precision/recall/FPR/tỷ lệ cảnh báo của QUYẾT ĐỊNH CUỐI (blend + trigger KYA) tại các ngưỡng.
    Chưa gồm LLM Critic (chỉ nâng mức) và Hard Policy (chặn cứng theo hạn mức)."""
    cols = pkg["cols"]
    X = np.array([[r[0][c] for c in cols] for r in rows])
    y = np.array([r[1] for r in rows])
    an = _norm_scores(pkg, X)
    beh = np.array([r[2] for r in rows])
    vel = np.array([r[3] for r in rows])
    codes = [tuple(r[4]) if len(r) > 4 else () for r in rows]
    trig = np.array([bool(c) for c in codes])     # trigger KYA xác định (độc lập với điểm)
    final = np.array([F.blend(a, b, v) for a, b, v in zip(an, beh, vel)])
    out = {"n": int(len(y)), "n_positive": int(y.sum()), "positive_rate": round(float(y.mean()), 4) if len(y) else None}
    pos = int(y.sum())
    if 0 < pos < len(y):
        from sklearn.metrics import average_precision_score, roc_auc_score
        out["auc_ml_only"] = round(float(roc_auc_score(y, an)), 4)
        out["auc_final"] = round(float(roc_auc_score(y, final)), 4)
        out["ap_final"] = round(float(average_precision_score(y, final)), 4)
    names = ("KYA_or_above", "REVIEW_or_above", "BLOCK")
    for nm, th in zip(names, thresholds):
        flag = (final >= th) | (trig if nm == "KYA_or_above" else False)     # KYA = điểm ≥ ngưỡng HOẶC có trigger
        tp = int((flag & (y == 1)).sum())
        fp = int((flag & (y == 0)).sum())
        out[nm] = {"threshold": th, "alert_rate": round(float(flag.mean()), 4),
                   "recall": round(tp / pos, 4) if pos else None,
                   "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
                   "false_positive_rate": round(fp / max(int((y == 0).sum()), 1), 4)}
    # Nguyên nhân báo nhầm: trigger nào gây KYA cho giao dịch lành tính (để hiệu chỉnh chính sách)
    from collections import Counter
    fpc = Counter(c for flag_i, y_i, cs, f_i in zip(trig, y, codes, final) if flag_i and y_i == 0 and f_i < thresholds[0] for c in cs)
    out["kya_false_positive_by_trigger"] = dict(fpc.most_common(8))
    return out


def fit(domain, rows, seed=7, source="synthetic", holdout=None, save=True, extra=None):
    """Huấn luyện Isolation Forest trên rows (vec,label,...) – KHÔNG dùng nhãn để học (chỉ để báo cáo)."""
    from sklearn.ensemble import IsolationForest
    import joblib
    t = time.time()
    cols = F.COLS[domain]
    X = np.array([[r[0][c] for c in cols] for r in rows])
    y = np.array([r[1] for r in rows])
    model = IsolationForest(random_state=seed, n_jobs=1, **PARAMS)     # 256 mẫu/cây là chuẩn của Isolation Forest, file nhỏ
    model.fit(X)
    raw = -model.score_samples(X)
    p50, p995 = float(np.percentile(raw, 50)), float(np.percentile(raw, 99.5))
    pred = model.predict(X) == -1
    tp = int(((pred) & (y == 1)).sum())
    cols_hash = hashlib.sha256(",".join(cols).encode()).hexdigest()[:8]
    data_hash = hashlib.sha256(np.ascontiguousarray(X).tobytes() + json.dumps(PARAMS, sort_keys=True).encode()).hexdigest()[:8]
    version = f"{domain.lower()}-iforest-{time.strftime('%Y%m%d')}-{data_hash}"
    info = {"domain": domain, "version": version, "trained_at": int(time.time()), "code_version": CODE_VERSION,
            "n_samples": int(len(X)), "n_anomaly_injected": int(y.sum()), "data_source": source,
            "detected_injected_pct": round(100 * tp / max(int(y.sum()), 1), 1),
            "flagged_normal_pct": round(100 * int((pred & (y == 0)).sum()) / max(int((y == 0).sum()), 1), 1),
            "eval_note_insample": "Chỉ số trên chính dữ liệu huấn luyện (in-sample) – KHÔNG phản ánh hiệu quả thực tế.",
            "features": cols, "cols_hash": cols_hash, "params": dict(PARAMS), "p50": p50, "p995": p995}
    pkg = {"model": model, "cols": cols, "p50": p50, "p995": p995, "info": info}
    if holdout:
        info["holdout"] = evaluate_rows(pkg, holdout)
        info["holdout_note"] = "Đánh giá trên tập tách riêng (khác seed/khác khách). Dữ liệu tổng hợp → chỉ là kiểm tra hồi quy, chưa phải bằng chứng hiệu quả thực."
    if extra:
        info.update(extra)
    info["seconds"] = round(time.time() - t, 1)
    if save:
        path = model_path(domain)
        joblib.dump(pkg, path, compress=3)
        info["sha256"] = _sha256_file(path)
        info["size_bytes"] = os.path.getsize(path)
        if os.environ.get("AGENTMON_MODEL_ARCHIVE") == "1":
            os.makedirs(os.path.join(model_dir(), "archive"), exist_ok=True)
            shutil.copyfile(path, os.path.join(model_dir(), "archive", f"{version}.joblib"))
        entry = {k: info[k] for k in ("version", "trained_at", "code_version", "n_samples", "n_anomaly_injected", "data_source",
                                      "cols_hash", "params", "sha256", "size_bytes") if k in info}
        entry.update(file=os.path.basename(path), insample={"detected_injected_pct": info["detected_injected_pct"],
                                                              "flagged_normal_pct": info["flagged_normal_pct"]},
                     holdout=info.get("holdout"))
        _manifest_add(domain, entry)
        with _lock:
            _cache.pop(domain, None)
        LAST_TRAIN[domain] = info
    return info if save else (info, pkg)


def train(domain, n_personas=45, per=170, seed=7):
    rows = generate(domain, n_personas, per, seed)
    hold = generate(domain, max(10, n_personas // 3), per, seed + 1000, with_scores=True)
    return fit(domain, rows, seed, source=f"synthetic(seed={seed},personas={n_personas},per={per})", holdout=hold)


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
                if obj.get("cols") != F.COLS[domain]:      # đặc trưng đã đổi → bắt buộc huấn luyện lại
                    obj = None
            except Exception:
                obj = None
    if obj is None:
        train(domain)
        obj = joblib.load(path)
        mt = os.path.getmtime(path)
    obj["_sha"] = _sha256_file(path)
    with _lock:
        _cache[domain] = (mt, obj)
    return obj


def model_ref(domain):
    """Tham chiếu mô hình cho trace quyết định: version + SHA-256 + nguồn dữ liệu."""
    m = _load(domain)
    i = m["info"]
    return {"domain": domain, "version": i.get("version", "unversioned"), "sha256": m.get("_sha"), "trained_at": i.get("trained_at"),
            "n_samples": i.get("n_samples"), "data_source": i.get("data_source", "unknown"), "n_features": len(m["cols"])}


def integrity(domain):
    """So khớp SHA-256 file mô hình với MANIFEST (phát hiện file bị thay thế ngoài quy trình huấn luyện)."""
    m = _load(domain)
    cur = (read_manifest().get(domain) or {})
    ent = next((e for e in reversed(cur.get("history") or []) if e.get("version") == cur.get("current")), None)
    ok = bool(ent) and ent.get("sha256") == m.get("_sha")
    return {"ok": ok, "sha256": m.get("_sha"), "manifest_sha256": (ent or {}).get("sha256"), "manifest_version": cur.get("current")}


def status():
    out = {}
    for d in ("FX", "PAY"):
        try:
            info = dict(_load(d)["info"])
            info["integrity"] = integrity(d)
            out[d] = info
        except Exception as e:      # noqa: BLE001
            out[d] = {"error": str(e)[:100]}
    return out


def anomaly(domain, vec: dict) -> float:
    m = _load(domain)
    x = np.array([[vec[c] for c in m["cols"]]])
    return float(_norm_scores(m, x)[0])
