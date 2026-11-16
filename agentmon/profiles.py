"""Hồ sơ triển khai (demo / pilot / production) và kiểm tra mức sẵn sàng.
Đặt DEPLOY_PROFILE=demo|pilot|production. Không đặt: PRICING_ENVIRONMENT=production → pilot, còn lại → demo.
Chỉ khi DEPLOY_PROFILE=production được khai báo RÕ, ứng dụng KHÔNG khởi động nếu còn mục BLOCKER (xem readiness())."""
import os

PROFILES = {
    "demo": {
        "desc": "Trình diễn nội bộ: dữ liệu mô phỏng, Test Lab bật, thử thách nới lỏng.",
        "antibot": {"require_telemetry_sources": [], "block_without_nonce": False, "fail_closed": False},
    },
    "pilot": {
        "desc": "Chạy thử có kiểm soát với dữ liệu/khách hàng giới hạn, bắt buộc telemetry kênh trực tuyến, ghi nhật ký đầy đủ.",
        "antibot": {"block_without_nonce": False, "fail_closed": True},
    },
    "production": {
        "desc": "Vận hành thật: bắt buộc nonce chống replay, fail-closed, ngưỡng dò thẻ chặt hơn.",
        "antibot": {"block_without_nonce": True, "fail_closed": True, "card_enum_block": 4, "card_enum_challenge": 2,
                    "card_test_block": 5, "device_customers_block": 3, "device_customers_challenge": 2},
    },
}


def current() -> str:
    p = (os.environ.get("DEPLOY_PROFILE") or "").strip().lower()
    if p in PROFILES:
        return p
    env = (os.environ.get("PRICING_ENVIRONMENT") or "demo").strip().lower()
    return "pilot" if env == "production" else "demo"       # cấu hình cũ PRICING_ENVIRONMENT=production = pilot; hồ sơ production phải khai báo rõ


def ensemble_mode() -> str:
    """Chế độ các mô hình AI bổ sung (bot-người, gradient boosting giám sát): active = tác động quyết định; shadow = chỉ ghi nhận.
    Mặc định: demo active; pilot/production shadow cho tới khi kiểm chứng trên dữ liệu thật (đặt ENSEMBLE_MODE=active để bật)."""
    m = (os.environ.get("ENSEMBLE_MODE") or "").strip().lower()
    if m in ("active", "shadow"):
        return m
    return "active" if current() == "demo" else "shadow"


def antibot_overrides() -> dict:
    return dict(PROFILES[current()]["antibot"])


def _flag(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def readiness() -> list:
    """Danh sách kiểm tra. level: BLOCKER (không được lên production) | WARN (chấp nhận được ở pilot, cần xử lý) | OK."""
    p = current()
    prod, pilot = p == "production", p == "pilot"
    C = []

    def chk(cid, ok, level, msg, fix=""):
        C.append({"id": cid, "ok": bool(ok), "level": "OK" if ok else level, "message": msg, "fix": fix})

    sk, sg = os.environ.get("SECRET_KEY", ""), os.environ.get("API_SIGNING_SECRET", "")
    chk("SECRET_KEY", len(sk) >= 32, "BLOCKER", "SECRET_KEY ≥ 32 ký tự", "python -c \"import secrets;print(secrets.token_urlsafe(48))\"")
    chk("SIGNING_SECRET", len(sg) >= 32 and sg != sk, "BLOCKER", "API_SIGNING_SECRET ≥ 32 ký tự và khác SECRET_KEY")
    chk("CARD_VAULT_KEY", bool(os.environ.get("CARD_VAULT_KEY")), "BLOCKER" if prod else "WARN", "Có CARD_VAULT_KEY (khóa vault token thẻ)", "Lưu trong KMS/HSM")
    chk("REDIS", bool(os.environ.get("REDIS_URL")) or _flag("ALLOW_MEMORY_STORE"), "BLOCKER" if (prod or pilot) else "WARN",
        "Có Redis cho rate-limit/phiên/nonce (store RAM chỉ dùng demo, 1 worker)", "Đặt REDIS_URL")
    workers = int(os.environ.get("WEB_CONCURRENCY", "1") or 1)
    chk("REDIS_MULTIWORKER", not (workers > 1 and not os.environ.get("REDIS_URL")), "BLOCKER", "Nhiều worker bắt buộc dùng Redis")
    chk("LAB_OFF", not (_flag("AGENTMON_LAB") and prod), "BLOCKER", "Test Lab tắt ở production")
    chk("COOKIE_SECURE", _flag("SESSION_COOKIE_SECURE", "1" if prod else "0") or not prod, "BLOCKER" if prod else "WARN", "SESSION_COOKIE_SECURE=1 (HTTPS)")
    chk("TRUSTED_PROXY", _flag("TRUSTED_PROXY") or not (prod or pilot), "WARN", "TRUSTED_PROXY=1 khi chạy sau reverse proxy (đọc IP thật)")
    chk("DEMO_PASSWORD_UNSET", not (prod and os.environ.get("DEMO_PASSWORD")), "BLOCKER", "Không đặt DEMO_PASSWORD ở production (tài khoản demo)")
    db_path = os.environ.get("AGENTMON_DB", "")
    sqlite = (not db_path) or db_path.endswith((".db", ".sqlite", ".sqlite3")) or "sqlite" in db_path
    chk("DATABASE", not (prod and sqlite) or _flag("ALLOW_SQLITE_PRODUCTION"), "BLOCKER" if prod else "WARN",
        "CSDL production phải là PostgreSQL/Oracle (SQLite chỉ demo/pilot); khóa liên máy bằng advisory lock", "Chuyển CSDL; xem docs/DEPLOYMENT.md")
    chk("CORE_ADAPTER", (os.environ.get("CORE_ADAPTER") or "mock") != "mock", "BLOCKER" if prod else "WARN",
        "Dữ liệu khách/thẻ/số dư từ core banking thật (CORE_ADAPTER ≠ mock)", "Viết adapter thay app/customer/mock_db.py")
    chk("HUMAN_LLM_OFF", (os.environ.get("HUMAN_LLM_MODE") or "off") == "off", "WARN", "Không gọi LLM trên đường đi thời gian thực của người dùng (HUMAN_LLM_MODE=off)")
    chk("TURNSTILE", bool(os.environ.get("TURNSTILE_SITE_KEY") and os.environ.get("TURNSTILE_SECRET_KEY")), "BLOCKER" if prod else "WARN",
        "Có Turnstile/CAPTCHA cho thử thách Anti-Bot")
    chk("MFA_ROLES", bool(os.environ.get("MFA_REQUIRED_ROLES")) or not prod, "BLOCKER" if prod else "WARN", "MFA bắt buộc cho HQ/Quản trị chi nhánh")
    chk("AUDIT_LOG", bool(os.environ.get("AUDIT_LOG_FILE")), "WARN", "Có AUDIT_LOG_FILE (nhật ký kiểm toán bền vững, ghi một chiều)")
    chk("MODEL_ARCHIVE", _flag("AGENTMON_MODEL_ARCHIVE"), "WARN", "AGENTMON_MODEL_ARCHIVE=1 để tái lập mô hình cũ khi kiểm toán")
    try:
        from agentmon import ml
        st = ml.status()
        synth = any(str((st.get(d) or {}).get("data_source", "")).startswith("synthetic") for d in ("FX", "PAY"))
        chk("MODEL_REAL_DATA", not synth, "BLOCKER" if prod else "WARN", "Mô hình huấn luyện/kiểm chứng trên dữ liệu thật (hiện là dữ liệu tổng hợp)",
            "python -m agentmon.backtest --csv … --save-model")
        man = ml.read_manifest()
        extra_synth = [k for k in ("BOT", "GBM_FX", "GBM_PAY") if str(((man.get(k) or {}).get("history") or [{}])[-1].get("data_source", "")).startswith("synthetic")]
        chk("AI_ENSEMBLE_REAL_DATA", not extra_synth, "BLOCKER" if prod else "WARN", f"Mô hình bot–người và gradient boosting huấn luyện trên dữ liệu thật (còn tổng hợp: {', '.join(extra_synth) or 'không'})",
            "Huấn luyện lại bằng nhãn thật; trong lúc chờ chạy ENSEMBLE_MODE=shadow")
        chk("AI_ENSEMBLE_SHADOW", ensemble_mode() == "shadow" or not (prod or pilot), "WARN", "Mô hình AI bổ sung ở chế độ bóng (shadow) cho tới khi kiểm chứng trên dữ liệu thật")
        chk("FACE_AI_PROVIDER", (os.environ.get("FACE_AI_PROVIDER") or "demo") != "demo", "BLOCKER" if prod else "WARN",
            "Dùng dịch vụ Face-AI thật, đạt kiểm thử PAD độc lập (hiện embedding giả lập)", "Đặt FACE_AI_PROVIDER và tích hợp nhà cung cấp")
        chk("MODEL_INTEGRITY", all((st.get(d) or {}).get("integrity", {}).get("ok") for d in ("FX", "PAY")), "BLOCKER", "SHA-256 mô hình khớp MANIFEST")
    except Exception as e:      # noqa: BLE001
        chk("MODEL_LOAD", False, "BLOCKER", f"Không nạp được mô hình: {str(e)[:80]}")
    from agentmon import antibot_txn
    chk("ANTIBOT_FAIL_CLOSED", antibot_txn.cfg()["fail_closed"] or not prod, "BLOCKER" if prod else "WARN", "Anti-Bot giao dịch fail-closed (lỗi → chặn)")
    chk("ANTIBOT_NONCE", antibot_txn.cfg()["block_without_nonce"] or not prod, "WARN", "Bắt buộc nonce chống replay cho nguồn người dùng")
    return C


def enforce(app=None):
    """production: từ chối khởi động nếu còn BLOCKER. Các hồ sơ khác: chỉ ghi cảnh báo."""
    res = readiness()
    blockers = [c for c in res if c["level"] == "BLOCKER"]
    if current() == "production" and blockers:
        raise RuntimeError("Chưa đủ điều kiện production: " + "; ".join(f"{c['id']} ({c['message']})" for c in blockers))
    if app is not None:
        for c in res:
            if c["level"] in ("BLOCKER", "WARN"):
                app.logger.warning("[readiness:%s] %s – %s", current(), c["id"], c["message"])
    return res
