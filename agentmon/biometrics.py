"""SINH TRẮC KHUÔN MẶT – đăng ký mẫu (KYC) và đối chiếu (KYA) dùng cho ATM/Digibank.

Vai trò trong hệ thống: Monitor KHÔNG tự chụp/nhận diện ảnh. Dịch vụ Face-AI (camera ATM / app) trích xuất embedding và các chỉ số
chống giả mạo (PAD – ISO/IEC 30107-3) rồi gửi sang. Mô-đun này (1) lưu MẪU đã đăng ký (embedding) MÃ HÓA khi lưu, (2) so khớp embedding
gửi tới với mẫu đã đăng ký (cosine → điểm hiệu chỉnh), (3) kết luận verdict từ các chỉ số.

Quyền riêng tư: sinh trắc là dữ liệu cá nhân NHẠY CẢM – chỉ đăng ký khi có sự đồng ý; chỉ lưu embedding (không lưu ảnh); mã hóa Fernet
(khóa dẫn xuất từ CARD_VAULT_KEY – production dùng KMS/HSM); có thể xóa theo yêu cầu. Hiệu chỉnh ngưỡng khớp phải theo nhà cung cấp Face-AI (FAR/FRR).
"""
import base64
import hashlib
import json
import math
import os
import random
import time

from cryptography.fernet import Fernet

from agentmon import db

MODEL_NAME = "face-embedding-v1"
DIM = 128


def _fernet():
    k = os.environ.get("CARD_VAULT_KEY") or os.environ.get("API_SIGNING_SECRET") or os.environ.get("SECRET_KEY") or "demo-vault-key"
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("bio|" + k).encode()).digest()))


def _norm(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def cosine(a, b):
    if len(a) != len(b) or not a:
        raise ValueError("embedding khác số chiều")
    return sum(x * y for x, y in zip(_norm(a), _norm(b)))


def calibrate(cos: float) -> float:
    """Cosine → điểm khớp 0–1. HIỆU CHỈNH MẪU: thay bằng đường cong của nhà cung cấp Face-AI (theo FAR/FRR mục tiêu)."""
    return 1.0 / (1.0 + math.exp(-12.0 * (cos - 0.35)))


def demo_embedding(seed: str, noise: float = 0.0, dim: int = DIM, noise_seed=None):
    """Embedding giả lập xác định (chỉ để demo/test): cùng seed + nhiễu nhỏ = cùng một người; seed khác = người khác."""
    r = random.Random(hashlib.sha256(seed.encode()).hexdigest())
    base = [r.gauss(0, 1) for _ in range(dim)]
    if noise:
        rn = random.Random(noise_seed if noise_seed is not None else time.time_ns())
        base = [x + rn.gauss(0, noise) for x in base]
    return _norm(base)


def enroll(customer_id: str, embedding, consent: bool, consent_version: str = "v1", model: str = MODEL_NAME):
    if not consent:
        raise PermissionError("Chưa có sự đồng ý của khách hàng cho việc xử lý dữ liệu sinh trắc học.")
    if not isinstance(embedding, (list, tuple)) or len(embedding) < 16 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in embedding):
        raise ValueError("embedding không hợp lệ")
    v = _norm([float(x) for x in embedding])
    blob = _fernet().encrypt(json.dumps(v).encode()).decode()
    now = time.time()
    db.execute("INSERT OR REPLACE INTO biometric_templates(customer_id,blob,model,dim,enrolled_at,consent_at,consent_version,status) VALUES(?,?,?,?,?,?,?,'ACTIVE')",
               (customer_id, blob, model, len(v), now, now, consent_version))
    return {"customer_id": customer_id, "dim": len(v), "model": model}


def _load(customer_id):
    r = db.one("SELECT * FROM biometric_templates WHERE customer_id=? AND status='ACTIVE'", (customer_id,))
    if not r:
        return None
    return json.loads(_fernet().decrypt(r["blob"].encode()).decode())


def enrolled(customer_id) -> bool:
    return bool(db.one("SELECT 1 FROM biometric_templates WHERE customer_id=? AND status='ACTIVE'", (customer_id,)))


def delete(customer_id):
    """Quyền xóa dữ liệu sinh trắc theo yêu cầu của chủ thể dữ liệu."""
    db.execute("DELETE FROM biometric_templates WHERE customer_id=?", (customer_id,))


def match_score(customer_id, embedding):
    tpl = _load(customer_id)
    if tpl is None:
        return None
    return calibrate(cosine(tpl, [float(x) for x in embedding]))


def assess_face(sig: dict, customer_id: str, g: dict) -> dict:
    """Từ tín hiệu Face-AI → verdict. sig: face_present, faces_in_frame, face_match_score | _face_embedding, liveness_score,
    injection_attack_score, occlusion, capture_quality, camera_status (OK|OBSTRUCTED|TAMPERED|OFFLINE)."""
    hi, lo = g.get("face_match_high", 0.80), g.get("face_match_low", 0.50)
    cam = sig.get("camera_status", "OK")
    out = {"camera_status": cam, "faces_in_frame": sig.get("faces_in_frame"), "liveness": sig.get("liveness_score"),
           "injection": sig.get("injection_attack_score"), "quality": sig.get("capture_quality"), "occlusion": sig.get("occlusion"),
           "enrolled": enrolled(customer_id), "match": None, "reasons": []}
    m = sig.get("face_match_score")
    if m is None and sig.get("_face_embedding") is not None and out["enrolled"]:
        try:
            m = match_score(customer_id, sig["_face_embedding"])
        except ValueError:
            m = None
    out["match"] = None if m is None else round(float(m), 4)
    live, inj = sig.get("liveness_score"), sig.get("injection_attack_score")
    if cam == "TAMPERED":
        v = "CAMERA_TAMPER"
    elif cam == "OBSTRUCTED":
        v = "CAMERA_BLOCKED"
    elif cam == "OFFLINE":
        v = "CAMERA_OFFLINE"
    elif not sig.get("face_present", False):
        v = "NO_PERSON"
    elif (inj is not None and inj >= g.get("injection_fail", 0.60)) or (live is not None and live < g.get("liveness_fail", 0.50)):
        v = "PRESENTATION_ATTACK"
    elif (sig.get("faces_in_frame") or 1) >= 2:
        v = "MULTIPLE_FACES"
    elif not out["enrolled"] and m is None:
        v = "NOT_ENROLLED"
    elif (sig.get("capture_quality") is not None and sig["capture_quality"] < g.get("face_quality_min", 0.50)) or \
            (sig.get("occlusion") is not None and sig["occlusion"] > g.get("occlusion_max", 0.40)) or \
            (live is not None and live < g.get("liveness_min", 0.90)) or (inj is not None and inj > g.get("injection_max", 0.30)):
        v = "FACE_UNCERTAIN"
    elif m is None:
        v = "FACE_UNCERTAIN"
    elif m >= hi:
        v = "FACE_VERIFIED"
    elif m < lo:
        v = "FACE_MISMATCH"
    else:
        v = "FACE_UNCERTAIN"
    out["verdict"] = v
    return out
