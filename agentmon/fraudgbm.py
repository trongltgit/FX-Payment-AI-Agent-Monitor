"""MÔ HÌNH GIÁM SÁT THỨ HAI (gradient boosting, học có giám sát) – "ý kiến thứ hai" bên cạnh Isolation Forest không giám sát.
Đầu vào: vector đặc trưng + điểm hành vi + điểm velocity. Đầu ra: xác suất rủi ro 0–1.

Trung thực: nhãn hiện là nhãn TỔNG HỢP do bộ sinh gắn (vòng tròn với cách sinh dữ liệu) → chạy BÓNG (shadow: chỉ ghi nhận) ở pilot/production cho tới khi
huấn luyện lại bằng nhãn thật (`python -m agentmon.backtest --csv … --save-model`). Ở chế độ active chỉ được NÂNG cảnh báo (trigger SUPERVISED_HIGH_RISK), không bao giờ hạ."""
import os
import time

import numpy as np

from agentmon import features as F
from agentmon import ml
from agentmon.constants import CODE_VERSION

_cache = {}
HIGH = 0.85


def _x(vec, beh, vel, cols):
    return [vec[c] for c in cols] + [beh, vel]


def train(domain, seed=7):
    import joblib
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import average_precision_score, roc_auc_score
    t0 = time.time()
    cols = F.COLS[domain]
    rows = ml.generate(domain, 45, 170, seed, with_scores=True)
    hold = ml.generate(domain, 15, 170, seed + 1000, with_scores=True)
    X = np.array([_x(r[0], r[2], r[3], cols) for r in rows], dtype=float)
    y = np.array([r[1] for r in rows])
    Xh = np.array([_x(r[0], r[2], r[3], cols) for r in hold], dtype=float)
    yh = np.array([r[1] for r in hold])
    m = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.08, max_iter=150, random_state=seed).fit(X, y)
    p = m.predict_proba(Xh)[:, 1]
    flagged = p >= HIGH
    hm = {"n": int(len(yh)), "positive_rate": round(float(yh.mean()), 3), "auc": round(float(roc_auc_score(yh, p)), 4), "ap": round(float(average_precision_score(yh, p)), 4),
          "at_0.85": {"alert_rate": round(float(flagged.mean()), 4), "recall": round(float((flagged & (yh == 1)).sum() / max(int(yh.sum()), 1)), 4),
                      "precision": round(float((flagged & (yh == 1)).sum() / max(int(flagged.sum()), 1)), 4),
                      "false_positive_rate": round(float((flagged & (yh == 0)).sum() / max(int((yh == 0).sum()), 1)), 4)}}
    name = f"gbm_{domain.lower()}.joblib"
    path = os.path.join(ml.model_dir(), name)
    ver = f"gbm-{domain.lower()}-{time.strftime('%Y%m%d')}-{ml.hashlib.sha256(np.ascontiguousarray(X).tobytes()).hexdigest()[:8]}"
    info = {"version": ver, "cols": cols + ["behavior", "velocity"], "domain": domain, "n_samples": int(len(y)), "data_source": f"synthetic(seed={seed})", "code_version": CODE_VERSION,
            "holdout": hm, "trained_at": int(time.time())}
    joblib.dump({"model": m, "info": info, "cols": cols}, path, compress=3)
    ml._manifest_add("GBM_" + domain, {**{k: info[k] for k in ("version", "trained_at", "code_version", "n_samples", "data_source")}, "sha256": ml._sha256_file(path),
                                       "size_bytes": os.path.getsize(path), "file": name, "holdout": hm})
    _cache.pop(domain, None)
    info["seconds"] = round(time.time() - t0, 1)
    return info


def _load(domain):
    import joblib
    path = os.path.join(ml.model_dir(), f"gbm_{domain.lower()}.joblib")
    mt = os.path.getmtime(path) if os.path.exists(path) else None
    c = _cache.get(domain)
    if c and c[0] == mt and mt is not None:
        return c[1]
    obj = None
    if mt is not None:
        obj = joblib.load(path)
        if obj.get("cols") != F.COLS[domain]:
            obj = None
    if obj is None:
        train(domain)
        mt = os.path.getmtime(path)
        obj = joblib.load(path)
    _cache[domain] = (mt, obj)
    return obj


def prob(domain, vec, beh, vel):
    o = _load(domain)
    return float(o["model"].predict_proba(np.array([_x(vec, beh, vel, o["cols"])], dtype=float))[:, 1][0])


def version(domain):
    return _load(domain)["info"]["version"]
