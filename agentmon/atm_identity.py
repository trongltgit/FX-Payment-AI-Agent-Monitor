"""AI NHẬN DIỆN DANH TÍNH TẠI ATM: ai đang rút tiền – CHÍNH KHÁCH HÀNG, NGƯỜI KHÁC dùng thẻ, hay TỰ ĐỘNG HÓA/AI Agent?

Kết hợp: camera AI (khuôn mặt đã đăng ký, chống giả mạo PAD) + hành vi tại ATM (nhịp nhập PIN, số lần PIN sai, nhiều thẻ trên một ATM) +
xác nhận qua điện thoại của chủ thẻ (APP_CONFIRM = KYA của kênh ATM). ATM là thiết bị vật lý: AI Agent KHÔNG thể đứng trước ATM, nên
giao dịch ATM do Agent gửi là rút tiền mặt từ xa → luôn cần chủ thẻ xác nhận.

Kết luận `who`: CUSTOMER | THIRD_PARTY | NO_PERSON | SPOOF | UNKNOWN.  `floor` = mức quyết định tối thiểu (ALLOW/STEP_UP/REVIEW/BLOCK).
"""
from agentmon import biometrics, db

FACE_VERDICT_WHO = {"FACE_VERIFIED": "CUSTOMER", "FACE_MISMATCH": "THIRD_PARTY", "PRESENTATION_ATTACK": "SPOOF", "NO_PERSON": "NO_PERSON"}


def assess(a: dict, bio: dict | None, g: dict, now: float) -> dict:
    amt = float(a.get("amount_vnd") or 0)
    cid = a.get("customer_id") or ""
    out = {"verdict": "NO_BIOMETRIC_CHANNEL", "who": "UNKNOWN", "floor": "ALLOW", "step_up_method": None, "triggers": [], "fraud": [], "hard": None,
           "advice": [], "behavior": [], "face": None}
    unenr = g.get("atm_unenrolled_stepup_above_vnd", 3_000_000)
    if bio is not None:
        face = biometrics.assess_face(bio, cid, g)
        out["face"] = face
        v = face["verdict"]
        out["verdict"] = v
        out["who"] = FACE_VERDICT_WHO.get(v, "UNKNOWN")
        if v == "FACE_VERIFIED":
            out["advice"].append("Chủ thẻ trực tiếp, khuôn mặt khớp và có liveness")
        elif v == "FACE_MISMATCH":
            out["floor"], out["hard"] = "BLOCK", f"Khuôn mặt không khớp chủ thẻ (điểm {face['match']:.2f}) – nghi người khác dùng thẻ"
            out["fraud"].append(("ATM_THIRD_PARTY_USE", f"Khuôn mặt không khớp mẫu đã đăng ký ({face['match']:.2f})", "HIGH"))
            out["advice"] += ["Từ chối giao dịch", "Cân nhắc giữ thẻ tại ATM", "Thông báo chủ thẻ qua app"]
        elif v == "PRESENTATION_ATTACK":
            out["floor"], out["hard"] = "BLOCK", "Phát hiện tấn công giả mạo sinh trắc (ảnh/video/mặt nạ/virtual camera)"
            out["fraud"].append(("ATM_SPOOF_ATTACK", "Liveness thấp hoặc phát hiện injection/deepfake", "HIGH"))
            out["advice"] += ["Từ chối", "Lưu bằng chứng camera", "Báo bộ phận an ninh"]
        elif v == "NO_PERSON":
            out["floor"], out["hard"] = "BLOCK", "Không có người trước ATM (camera hoạt động) – nghi rút tiền từ xa/relay/malware"
            out["fraud"].append(("ATM_NO_PERSON", "Giao dịch ATM không có người trước máy", "HIGH"))
            out["advice"] += ["Từ chối", "Kiểm tra ATM (jackpotting/relay)"]
        elif v in ("CAMERA_BLOCKED", "CAMERA_TAMPER"):
            out["floor"] = "REVIEW" if (amt >= g.get("atm_camera_blocked_review_above_vnd", 5_000_000) or v == "CAMERA_TAMPER") else "STEP_UP"
            out["step_up_method"] = "APP_CONFIRM"
            out["triggers"].append(("ATM_CAMERA_BLOCKED", "Camera ATM bị che/can thiệp" if v == "CAMERA_BLOCKED" else "Camera ATM bị can thiệp (tamper)"))
            out["fraud"].append(("ATM_CAMERA_BLOCKED", "Che/can thiệp camera ATM – dấu hiệu chuẩn bị gian lận", "HIGH" if v == "CAMERA_TAMPER" else "MED"))
        elif v == "CAMERA_OFFLINE":
            if amt >= unenr:
                out["floor"], out["step_up_method"] = "STEP_UP", "APP_CONFIRM"
                out["triggers"].append(("ATM_CAMERA_OFFLINE", "Camera ATM ngừng hoạt động, số tiền cần xác nhận qua điện thoại"))
        elif v == "MULTIPLE_FACES":
            out["floor"], out["step_up_method"] = "STEP_UP", "APP_CONFIRM"
            out["triggers"].append(("ATM_MULTIPLE_FACES", f"{bio.get('faces_in_frame')} khuôn mặt trước ATM (nhìn trộm/ép buộc)"))
            out["fraud"].append(("ATM_COERCION_OR_SURFING", "Nhiều người trước ATM", "MED"))
        elif v == "FACE_UNCERTAIN":
            out["floor"], out["step_up_method"] = "STEP_UP", "APP_CONFIRM"
            out["triggers"].append(("ATM_FACE_UNCERTAIN", "Khuôn mặt chưa đủ chắc chắn – cần chủ thẻ xác nhận trên điện thoại (KYA)"))
        elif v == "NOT_ENROLLED":
            if amt >= unenr:
                out["floor"], out["step_up_method"] = "STEP_UP", "APP_CONFIRM"
                out["triggers"].append(("ATM_NOT_ENROLLED", "Chủ thẻ chưa đăng ký khuôn mặt, số tiền cần xác nhận qua điện thoại"))
    # Hành vi tại ATM (không cần camera)
    cv, n = a.get("pin_entry_cv"), a.get("pin_digits") or 0
    if cv is not None and n >= 4 and cv < 0.05:
        out["behavior"].append((0.25, "Nhịp nhập PIN đều như máy (nghi tự động hóa/thiết bị chèn)"))
        out["triggers"].append(("ATM_PIN_AUTOMATED", "Nhập PIN với nhịp đều như máy"))
        out["fraud"].append(("ATM_PIN_AUTOMATED", "PIN nhập theo nhịp máy", "MED"))
    if (a.get("pin_attempts") or 0) >= 2:
        out["behavior"].append((0.15, f"{a['pin_attempts']} lần nhập PIN"))
    atm = a.get("merchant")
    if atm and cid:
        n_cards = db.one("SELECT COUNT(DISTINCT customer_id) n FROM actions WHERE merchant=? AND kind='ATM_WITHDRAWAL' AND ts>? AND sim!=2", (atm, now - 600))
        n_cards = (n_cards or {}).get("n", 0)
        if n_cards >= g.get("atm_cards_collect_n", 4):
            out["behavior"].append((0.30, f"{n_cards} thẻ của các khách khác nhau trên cùng ATM trong 10 phút"))
            out["triggers"].append(("ATM_CARD_COLLECTION", f"{n_cards} thẻ khác chủ trên một ATM/10 phút (thu gom thẻ/skimming)"))
            out["fraud"].append(("ATM_CARD_COLLECTION", "Nhiều thẻ của nhiều chủ trên cùng ATM", "MED"))
    return out
