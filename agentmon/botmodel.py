"""MÔ HÌNH AI PHÂN BIỆT BOT – NGƯỜI (Tầng 1): HistGradientBoosting học có giám sát trên đặc trưng sinh trắc hành vi phiên
(thời gian suy nghĩ, chuột/phím, entropy đường đi chuột, biến thiên nhịp phím, header, điểm Anti-Bot web, tuổi phiên, thiết bị).

Trung thực: huấn luyện trên dữ liệu TỔNG HỢP (3 loại bot: ngây thơ / có trễ / mô phỏng người nâng cao). Số liệu holdout chỉ là kiểm tra hồi quy;
cần dữ liệu thật (nhãn bot từ SOC, nhãn người từ phiên đã xác thực MFA/sinh trắc) trước khi dựa vào. Vì vậy chạy ở chế độ BÓNG (shadow) ở pilot/production
cho tới khi được kiểm chứng (profiles.ensemble_mode)."""
import math
import os
import random
import time

import numpy as np

from agentmon import ml
from agentmon.constants import CODE_VERSION

FEATURES = ["think_log", "ptr_log", "key_log", "ptr_entropy", "key_cv", "scroll_log", "focus_changes", "header", "web_score", "session_age_log", "device_known", "attested"]
_cache = {}


def vectorize(s: dict):
    nan = float("nan")

    def lg(v):
        return math.log1p(float(v)) if v is not None else nan

    def f(v, d=nan):
        return float(v) if v is not None else d
    return [lg(s.get("think_time_ms")), lg(s.get("pointer_events")), lg(s.get("key_events")), f(s.get("pointer_path_entropy")), f(s.get("key_interval_cv")),
            lg(s.get("scroll_events")), f(s.get("focus_changes")), f(s.get("header_score"), 0.0) / 100.0,
            (f(s.get("anti_bot_score"), 0.0) / 100.0), lg(s.get("session_age_s")), 1.0 if s.get("device_known") else 0.0, 1.0 if s.get("device_attested") else 0.0]


def _poisson(r, lam):
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        k += 1
        p *= r.random()
        if p <= L:
            return k - 1


def synth(n, seed):
    """Dữ liệu tổng hợp CÓ CHỦ ĐÍCH chồng lấn: bot nâng cao gần như giống người; người dùng trình quản lý mật khẩu/công nghệ hỗ trợ trông giống bot."""
    r = random.Random(seed)
    X, y = [], []
    for _ in range(n):
        bot = r.random() < 0.45
        if not bot:
            u = r.random()
            if u < 0.10:      # người "khác thường": autofill/trình quản lý mật khẩu/công nghệ hỗ trợ – nhanh, ít chuột, ít phím
                s = dict(think_time_ms=r.uniform(250, 1200), pointer_events=_poisson(r, 2) if r.random() < 0.6 else None, key_events=_poisson(r, 2) if r.random() < 0.6 else None,
                         pointer_path_entropy=r.uniform(0.2, 0.8) if r.random() < 0.5 else None, key_interval_cv=r.uniform(0.0, 0.4) if r.random() < 0.4 else None,
                         scroll_events=_poisson(r, 2), focus_changes=r.randint(0, 2), header_score=r.uniform(0, 45), anti_bot_score=r.uniform(5, 60),
                         session_age_s=r.lognormvariate(math.log(150), 0.9), device_known=r.random() < 0.6, device_attested=r.random() < 0.3)
            else:
                tele = r.random() > 0.10
                s = dict(think_time_ms=r.lognormvariate(math.log(4000), 0.7), pointer_events=_poisson(r, 16) if tele else None, key_events=_poisson(r, 13) if tele else None,
                         pointer_path_entropy=r.betavariate(5, 2.2) if tele else None, key_interval_cv=r.uniform(0.15, 0.9) if tele else None, scroll_events=_poisson(r, 5),
                         focus_changes=r.randint(0, 3), header_score=r.uniform(0, 35), anti_bot_score=r.uniform(0, 45), session_age_s=r.lognormvariate(math.log(280), 0.9),
                         device_known=r.random() < 0.65, device_attested=r.random() < 0.40)
        else:
            t = r.random()
            if t < 0.30:      # ngây thơ
                tele = r.random() < 0.5
                s = dict(think_time_ms=r.uniform(20, 400), pointer_events=0 if tele else None, key_events=0 if tele else None, pointer_path_entropy=None, key_interval_cv=None,
                         scroll_events=0, focus_changes=0, header_score=r.uniform(30, 95), anti_bot_score=r.uniform(45, 100), session_age_s=r.uniform(1, 40),
                         device_known=r.random() < 0.08, device_attested=False)
            elif t < 0.65:    # có trễ ngẫu nhiên
                s = dict(think_time_ms=r.uniform(600, 3500), pointer_events=_poisson(r, 4), key_events=_poisson(r, 5), pointer_path_entropy=r.uniform(0.1, 0.55),
                         key_interval_cv=r.uniform(0.0, 0.18), scroll_events=r.randint(0, 2), focus_changes=r.randint(0, 1), header_score=r.uniform(5, 60), anti_bot_score=r.uniform(20, 85),
                         session_age_s=r.uniform(5, 150), device_known=r.random() < 0.12, device_attested=False)
            else:             # mô phỏng người nâng cao (chồng lấn mạnh với người thật)
                s = dict(think_time_ms=r.lognormvariate(math.log(3200), 0.6), pointer_events=_poisson(r, 12), key_events=_poisson(r, 11), pointer_path_entropy=r.betavariate(4, 2.5),
                         key_interval_cv=r.uniform(0.12, 0.75), scroll_events=_poisson(r, 4), focus_changes=r.randint(0, 2), header_score=r.uniform(0, 40),
                         anti_bot_score=r.uniform(5, 60), session_age_s=r.lognormvariate(math.log(200), 0.8), device_known=r.random() < 0.25, device_attested=r.random() < 0.05)
        X.append(vectorize(s))
        y.append(1 if bot else 0)
    return np.array(X, dtype=float), np.array(y)


def train(seed=7):
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score, roc_curve
    t0 = time.time()
    X, y = synth(7000, seed)
    Xh, yh = synth(3000, seed + 1000)
    m = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08, max_iter=150, random_state=seed).fit(X, y)
    p = m.predict_proba(Xh)[:, 1]
    fpr, tpr, _ = roc_curve(yh, p)
    rec_at_1 = float(tpr[np.searchsorted(fpr, 0.01, side="right") - 1])
    hold = {"n": int(len(yh)), "bot_rate": round(float(yh.mean()), 3), "auc": round(float(roc_auc_score(yh, p)), 4), "ap": round(float(average_precision_score(yh, p)), 4),
            "recall_at_fpr_1pct": round(rec_at_1, 4), "flag_at_0.85": {"bot_recall": round(float(((p >= 0.85) & (yh == 1)).sum() / max(int(yh.sum()), 1)), 4),
                                                                      "human_flagged": round(float(((p >= 0.85) & (yh == 0)).sum() / max(int((yh == 0).sum()), 1)), 4)}}
    path = os.path.join(ml.model_dir(), "botmodel.joblib")
    info = {"version": f"bot-hgb-{time.strftime('%Y%m%d')}-{ml.hashlib.sha256(np.ascontiguousarray(X).tobytes()).hexdigest()[:8]}", "features": FEATURES, "n_samples": int(len(y)),
            "data_source": f"synthetic(seed={seed})", "code_version": CODE_VERSION, "holdout": hold, "trained_at": int(time.time())}
    joblib.dump({"model": m, "info": info}, path, compress=3)
    info["sha256"], info["size_bytes"] = ml._sha256_file(path), os.path.getsize(path)
    ml._manifest_add("BOT", {**{k: info[k] for k in ("version", "trained_at", "code_version", "n_samples", "data_source", "sha256", "size_bytes")}, "file": "botmodel.joblib", "holdout": hold})
    _cache.clear()
    info["seconds"] = round(time.time() - t0, 1)
    return info


def _load():
    import joblib
    path = os.path.join(ml.model_dir(), "botmodel.joblib")
    mt = os.path.getmtime(path) if os.path.exists(path) else None
    c = _cache.get("m")
    if c and c[0] == mt and mt is not None:
        return c[1]
    if mt is None:
        train()
        mt = os.path.getmtime(path)
    obj = joblib.load(path)
    _cache["m"] = (mt, obj)
    return obj


def score(session: dict):
    """Xác suất bot 0–1; None nếu phiên không có đủ tín hiệu hành vi (ít hơn 2 trong think/pointer/key)."""
    have = sum(1 for k in ("think_time_ms", "pointer_events", "key_events") if session.get(k) is not None)
    if have < 2:
        return None
    m = _load()["model"]
    return float(m.predict_proba(np.array([vectorize(session)], dtype=float))[:, 1][0])


def status():
    o = _load()
    return {**o["info"], "mode": __import__("agentmon.profiles", fromlist=["x"]).ensemble_mode()}
