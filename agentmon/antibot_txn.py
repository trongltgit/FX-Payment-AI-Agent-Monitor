"""TẦNG 1 – ANTI-BOT CẤP GIAO DỊCH (chạy TRƯỚC AI Agent Monitor, cho MỌI giao dịch: FX, thẻ mọi loại, chuyển tiền, QR/hóa đơn, mua sắm online).

Mục tiêu: phân biệt BOT THẬT (tự động trái phép) với NGƯỜI THẬT và với TỰ ĐỘNG HÓA ĐƯỢC PHÉP (AI Agent đã đăng ký có khóa hợp lệ).
Cách làm: sổ chứng cứ (evidence ledger) – mỗi tín hiệu cộng điểm vào phía "bot" hoặc phía "người"; luật quyết định minh bạch, giải thích được.

Lớp phân loại (bot_class):
  HUMAN_VERIFIED        bằng chứng người mạnh, không có dấu hiệu bot            → ALLOW
  HUMAN_LIKELY          giống người, bằng chứng chưa đủ mạnh                    → ALLOW (đẩy điểm sang Monitor)
  AUTOMATION_AUTHORIZED AI Agent có khóa hợp lệ, hành vi tự động là BÌNH THƯỜNG → ALLOW (Monitor xử lý như AGENT)
  SUSPECT               mâu thuẫn/đáng ngờ (nghi bot không khai báo, khóa Agent bị người dùng, ...) → CHALLENGE
  MALICIOUS_BOT         tự động trái phép, tấn công thẻ/replay/IP bị cấm         → BLOCK

KHÔNG thay thế bộ Anti-Bot web (app/guard.py, services/bot_defense.py) mà BỔ SUNG: điểm bot của phiên web (nếu có) được đưa vào làm một tín hiệu.
"""
import json
import re
import statistics
import time

from agentmon import botmodel, db, profiles
from services import bot_defense
from utils import store

HUMAN_VERIFIED, HUMAN_LIKELY, AUTOMATION_AUTHORIZED, SUSPECT, MALICIOUS_BOT = (
    "HUMAN_VERIFIED", "HUMAN_LIKELY", "AUTOMATION_AUTHORIZED", "SUSPECT", "MALICIOUS_BOT")
ALLOW, CHALLENGE, BLOCK = "ALLOW", "CHALLENGE", "BLOCK"

HEADLESS_UA = re.compile(r"(headless|phantomjs|selenium|puppeteer|playwright|webdriver|python-requests|python-urllib|curl/|wget/|go-http-client|"
                         r"okhttp(?!.*bank)|libwww|httpclient|scrapy|axios/|node-fetch)", re.I)
ONLINE_SOURCES = ("PORTAL", "DIGIBANK", "DIGIBIZ")
CARD_KINDS_AB = ("ONLINE_PURCHASE", "CARD_PAYMENT", "ATM_WITHDRAWAL", "WALLET_PAYMENT", "BILL_PAYMENT", "QR_PAYMENT")

# Ngưỡng mặc định (profiles.py ghi đè theo demo/pilot/production)
DEFAULTS = {
    "think_time_bot_ms": 300,          # xác nhận giao dịch nhanh hơn ngưỡng này: không phải người
    "think_time_human_ms": 1200,       # từ ngưỡng này trở lên (kèm telemetry) là hành vi người
    "cadence_min_requests": 8, "cadence_cv_max": 0.08, "cadence_window_s": 300,
    "card_enum_challenge": 3, "card_enum_block": 5, "card_enum_window_s": 600,          # số thẻ khác nhau trên cùng IP/thiết bị
    "card_test_small_vnd": 50_000, "card_test_block": 6, "card_test_window_s": 600,     # chuỗi giao dịch nhỏ (dò thẻ)
    "device_customers_challenge": 3, "device_customers_block": 4,                       # số khách khác nhau dùng chung 1 thiết bị / 24h
    "ip_rate_challenge_per_min": 120, "ip_rate_block_per_min": 600,
    "decline_ratio_block": 0.6, "decline_min": 4,
    "web_bot_score_suspect": 40, "web_bot_score_bot": 70,
    "header_score_suspect": 40,
    "stale_request_s": 300,
    "require_telemetry_sources": list(ONLINE_SOURCES),       # kênh trực tuyến phải gửi telemetry (pointer/key/think-time)
    "block_without_nonce": False,                            # production: bắt buộc nonce chống replay cho nguồn người dùng
    "bio_injection_fail": 0.60, "bio_liveness_fail": 0.50, "bio_liveness_good": 0.90, "bio_injection_max": 0.30,
    "fail_closed": True,                                     # lỗi hệ thống chống bot → chặn (tiền) thay vì cho qua
}


def cfg():
    from agentmon import profiles
    c = dict(DEFAULTS)
    c.update(profiles.antibot_overrides())
    return c


def _ev(side, signal, points, detail=""):
    return {"side": side, "signal": signal, "points": points, "detail": detail}


def _cv(ts_list):
    if len(ts_list) < 3:
        return None
    gaps = [b - a for a, b in zip(ts_list, ts_list[1:]) if b >= a]
    if len(gaps) < 2:
        return None
    m = statistics.mean(gaps)
    return (statistics.pstdev(gaps) / m) if m > 0 else 0.0


def _record(key, payload, keep):
    store.events_add(key, payload, keep_seconds=keep)


def _distinct(key, window):
    return {p for _, p in store.events_recent(key, window) if p}


def assess(req: dict) -> dict:
    """req: credential, ip, ua, header_score, source_system, agent_id, session{...}, txn{customer_id, kind, domain, amount, card_ref}."""
    C = cfg()
    ses = req.get("session") or {}
    txn = req.get("txn") or {}
    cred = req.get("credential") or "NONE"
    declared = "AGENT" if cred == "AGENT_KEY" else "HUMAN"
    ip, ua = req.get("ip") or "unknown", req.get("ua") or ""
    dev = ses.get("device_id") or ""
    cid = txn.get("customer_id") or ""
    kind = txn.get("kind") or ""
    amount = float(txn.get("amount") or 0)
    bot, human, rules, evid = 0, 0, [], []

    def add(side, signal, pts, detail=""):
        nonlocal bot, human
        evid.append(_ev(side, signal, pts, detail))
        if side == "BOT":
            bot += pts
        else:
            human += pts

    hard = None   # (rule, class, action, detail)

    # ---------------- 0. Điều kiện chặn cứng (không cần cân nhắc) ----------------
    if cred == "NONE":
        hard = ("NO_CREDENTIAL", MALICIOUS_BOT, BLOCK, "Không có thông tin xác thực hợp lệ")
    elif bot_defense.is_ip_banned(ip):
        hard = ("IP_BANNED", MALICIOUS_BOT, BLOCK, "IP đang bị Anti-Bot cấm")
    nonce = ses.get("nonce")
    if nonce and not store.setnx(f"ab:nonce:{nonce}", "1", ttl=3600):
        hard = hard or ("REPLAY", MALICIOUS_BOT, BLOCK, "Nonce đã được dùng (replay)")
    elif not nonce and declared == "HUMAN" and C["block_without_nonce"]:
        hard = hard or ("NO_NONCE", SUSPECT, CHALLENGE, "Thiếu nonce chống replay")
    cts = ses.get("ts")
    if cts is not None:
        try:
            if abs(store.now() - float(cts)) > C["stale_request_s"]:
                hard = hard or ("STALE_REQUEST", MALICIOUS_BOT, BLOCK, "Dấu thời gian phía client lệch > %ds (replay/đồng hồ sai)" % C["stale_request_s"])
        except (TypeError, ValueError):
            hard = hard or ("BAD_TS", SUSPECT, CHALLENGE, "Dấu thời gian không hợp lệ")

    # ---------------- 0b. Sinh trắc/camera: tấn công giả mạo là chặn cứng ----------------
    bio = ses.get("biometric") if isinstance(ses.get("biometric"), dict) else None
    if bio and bio.get("face_present") and ((bio.get("injection_attack_score") or 0) >= C["bio_injection_fail"] or
                                            (bio.get("liveness_score") is not None and bio["liveness_score"] < C["bio_liveness_fail"])):
        hard = hard or ("PRESENTATION_ATTACK", MALICIOUS_BOT, BLOCK, "Tấn công giả mạo sinh trắc (liveness thấp/injection/deepfake)")
    elif bio and bio.get("camera_status", "OK") == "OK" and bio.get("face_present") is False and req.get("source_system") == "ATM_SWITCH":
        hard = hard or ("NO_PERSON_AT_ATM", MALICIOUS_BOT, BLOCK, "Giao dịch ATM nhưng camera hoạt động không thấy người trước máy (rút tiền từ xa/relay/malware)")

    # ---------------- 1. Ghi nhận quan sát (để các luật vận tốc bên dưới đếm cả giao dịch hiện tại) ----------------
    _record(f"ab:ip:{ip}", "", 120)
    if dev:
        _record(f"ab:dev:{dev}", "", 120)
    if cid:
        _record(f"ab:cad:{declared}:{cid}", "", C["cadence_window_s"] + 30)
    card_ref = txn.get("card_ref")
    is_card = kind in CARD_KINDS_AB
    if is_card and card_ref:
        _record(f"ab:cards:ip:{ip}", card_ref, C["card_enum_window_s"] + 30)
        if dev:
            _record(f"ab:cards:dev:{dev}", card_ref, C["card_enum_window_s"] + 30)
    if is_card and 0 < amount < C["card_test_small_vnd"]:
        _record(f"ab:small:{dev or ip}", "", C["card_test_window_s"] + 30)
    if dev and cid:
        _record(f"ab:devcust:{dev}", cid, 86400)

    # ---------------- 2. Tấn công đặc thù thẻ/tài khoản (áp cho mọi loại người thực hiện) ----------------
    if is_card:
        n_cards = max(len(_distinct(f"ab:cards:ip:{ip}", C["card_enum_window_s"])), len(_distinct(f"ab:cards:dev:{dev}", C["card_enum_window_s"])) if dev else 0)
        if n_cards >= C["card_enum_block"]:
            hard = hard or ("CARD_ENUMERATION", MALICIOUS_BOT, BLOCK, f"{n_cards} thẻ khác nhau từ cùng IP/thiết bị trong {C['card_enum_window_s'] // 60} phút (dò BIN/thẻ)")
        elif n_cards >= C["card_enum_challenge"]:
            add("BOT", "CARD_ENUMERATION_WARN", 4, f"{n_cards} thẻ khác nhau từ cùng IP/thiết bị")
        small = store.events_count(f"ab:small:{dev or ip}", C["card_test_window_s"])
        if small >= C["card_test_block"]:
            hard = hard or ("CARD_TESTING", MALICIOUS_BOT, BLOCK, f"{small} giao dịch giá trị nhỏ liên tiếp (card testing)")
        dec = store.events_count(f"ab:decl:{ip}", C["card_test_window_s"])
        tot = store.events_count(f"ab:ip:{ip}", C["card_test_window_s"])
        if dec >= C["decline_min"] and tot and dec / tot >= C["decline_ratio_block"]:
            hard = hard or ("DECLINE_STORM", MALICIOUS_BOT, BLOCK, f"{dec}/{tot} giao dịch bị từ chối từ cùng IP")
    if dev:
        nc = len(_distinct(f"ab:devcust:{dev}", 86400))
        if nc >= C["device_customers_block"]:
            hard = hard or ("DEVICE_FARM", MALICIOUS_BOT, BLOCK, f"{nc} khách hàng khác nhau dùng chung một thiết bị trong 24 giờ (trang trại tài khoản)")
        elif nc >= C["device_customers_challenge"]:
            add("BOT", "DEVICE_SHARED", 3, f"{nc} khách dùng chung thiết bị")
    rate = store.events_count(f"ab:ip:{ip}", 60) if declared == "HUMAN" else 0       # Agent: đã có giới hạn theo khóa ở gateway
    if rate >= C["ip_rate_block_per_min"]:
        hard = hard or ("IP_FLOOD", MALICIOUS_BOT, BLOCK, f"{rate} yêu cầu/phút từ một IP")
    elif rate >= C["ip_rate_challenge_per_min"]:
        add("BOT", "IP_RATE_HIGH", 3, f"{rate} yêu cầu/phút từ một IP")

    # ---------------- 3. Tự động hóa ĐƯỢC PHÉP (AI Agent có khóa) ----------------
    if declared == "AGENT":
        # Agent tự động là BÌNH THƯỜNG: không phạt nhịp đều/thiếu telemetry. Chỉ kiểm tra dấu hiệu "người dùng chung khóa Agent".
        interactive = (ses.get("pointer_events") or 0) >= 3 or (ses.get("key_events") or 0) >= 3
        if interactive:
            add("HUMAN", "INTERACTIVE_TELEMETRY_ON_AGENT_KEY", 4, "Có chuột/bàn phím trong yêu cầu dùng khóa Agent → khóa bị người dùng chung?")
        if ses.get("ip_reputation") in ("TOR", "PROXY"):
            add("BOT", "AGENT_FROM_ANONYMIZER", 3, f"Agent gọi từ {ses['ip_reputation']}")
        if hard:
            cls, act, note = hard[1], hard[2], hard[3]
        elif interactive:
            cls, act, note = SUSPECT, CHALLENGE, "Khóa Agent có dấu hiệu bị NGƯỜI sử dụng trực tiếp (telemetry tương tác)"
            rules.append("AGENT_KEY_USED_BY_HUMAN")
        elif ses.get("ip_reputation") in ("TOR", "PROXY"):
            cls, act, note = SUSPECT, CHALLENGE, "Agent gọi từ mạng ẩn danh"
            rules.append("AGENT_FROM_ANONYMIZER")
        else:
            cls, act, note = AUTOMATION_AUTHORIZED, ALLOW, "AI Agent có khóa hợp lệ – tự động hóa được phép"
        if hard:
            rules.append(hard[0])
        return _finish(req, declared, cls, act, bot, human, rules, evid, note, C, ses)

    # ---------------- 4. NGƯỜI (phiên người dùng): sổ chứng cứ bot vs người ----------------
    think = ses.get("think_time_ms")
    ptr, keys = ses.get("pointer_events") or 0, ses.get("key_events") or 0
    has_telemetry = think is not None or ptr or keys
    # --- bằng chứng BOT
    if HEADLESS_UA.search(ua):
        add("BOT", "AUTOMATION_USER_AGENT", 4, ua[:60])
    hs = req.get("header_score") or 0
    if hs >= C["header_score_suspect"]:
        add("BOT", "HEADER_PROFILE", 3, f"header_score={hs}")
    wb = ses.get("anti_bot_score")
    if wb is not None:
        wb = float(wb)
        if wb >= C["web_bot_score_bot"]:
            add("BOT", "WEB_ANTIBOT_HIGH", 4, f"Anti-Bot web {wb:.0f}/100")
        elif wb >= C["web_bot_score_suspect"]:
            add("BOT", "WEB_ANTIBOT_MEDIUM", 2, f"Anti-Bot web {wb:.0f}/100")
    if think is not None and think < C["think_time_bot_ms"]:
        add("BOT", "THINK_TIME_TOO_FAST", 3, f"Xác nhận sau {think} ms")
    cad = _cv([t for t, _ in store.events_recent(f"ab:cad:{declared}:{cid}", C["cadence_window_s"])]) if cid else None
    n_cad = store.events_count(f"ab:cad:{declared}:{cid}", C["cadence_window_s"]) if cid else 0
    if cad is not None and n_cad >= C["cadence_min_requests"] and cad < C["cadence_cv_max"]:
        add("BOT", "METRONOME_CADENCE", 3, f"{n_cad} yêu cầu, CV khoảng cách = {cad:.3f}")
    if req.get("source_system") in C["require_telemetry_sources"] and not has_telemetry:
        add("BOT", "NO_TELEMETRY_ON_ONLINE_CHANNEL", 2, "Kênh trực tuyến không gửi telemetry người dùng")
    if ses.get("ip_reputation") in ("TOR", "PROXY", "DATACENTER"):
        add("BOT", "IP_REPUTATION", 2, str(ses["ip_reputation"]))
    # --- mô hình AI bot–người (học có giám sát) + sinh trắc
    extra = {"ml_bot_prob": None, "ml_mode": profiles.ensemble_mode()}
    try:
        mp = botmodel.score(dict(ses, header_score=hs))
    except Exception:      # noqa: BLE001
        mp = None
    if mp is not None:
        extra["ml_bot_prob"] = round(mp, 4)
        if extra["ml_mode"] == "active":
            if mp >= 0.85:
                add("BOT", "ML_BOT_HIGH", 3, f"Mô hình bot–người: {mp:.2f}")
            elif mp >= 0.60:
                add("BOT", "ML_BOT_MEDIUM", 2, f"Mô hình bot–người: {mp:.2f}")
            elif mp <= 0.15:
                add("HUMAN", "ML_HUMAN_HIGH", 2, f"Mô hình bot–người: {mp:.2f}")
        else:
            evid.append(_ev("SHADOW", "ML_BOT_PROB", 0, f"p={mp:.2f} (chế độ bóng – chưa tác động)"))
    if bio:
        if bio.get("face_present") and (bio.get("liveness_score") or 0) >= C["bio_liveness_good"] and (bio.get("injection_attack_score") or 0) <= C["bio_injection_max"]:
            add("HUMAN", "BIOMETRIC_LIVENESS", 4, f"Liveness {bio['liveness_score']:.2f}: có người thật trước camera")
        if (bio.get("face_match_score") or 0) >= 0.80:
            add("HUMAN", "FACE_MATCHED_ENROLLED", 2, f"Khuôn mặt khớp mẫu đã đăng ký ({bio['face_match_score']:.2f})")
    # --- bằng chứng NGƯỜI
    if ses.get("device_attested"):
        add("HUMAN", "DEVICE_ATTESTED", 3, "Ứng dụng ngân hàng được chứng thực toàn vẹn (App Attest/Play Integrity)")
    if ses.get("device_known"):
        add("HUMAN", "KNOWN_DEVICE", 2, "Thiết bị đã gắn với tài khoản")
    if ses.get("pow_ok") or ses.get("turnstile_ok"):
        add("HUMAN", "CHALLENGE_PASSED", 2, "Đã vượt PoW/Turnstile")
    ma = ses.get("mfa_age_s")
    if ma is not None and 0 <= float(ma) <= 900:
        add("HUMAN", "RECENT_MFA", 2, f"MFA cách đây {float(ma):.0f}s")
    if (ptr >= 3 or keys >= 3) and think is not None and think >= C["think_time_human_ms"]:
        add("HUMAN", "HUMAN_TELEMETRY", 3, f"pointer={ptr}, key={keys}, think={think}ms")
    if hs and hs < 20 and not HEADLESS_UA.search(ua) and ua:
        add("HUMAN", "BROWSER_LIKE_HEADERS", 1, f"header_score={hs}")

    # ---------------- 5. Quyết định (bảng điều kiện) ----------------
    if hard:
        cls, act, note = hard[1], hard[2], hard[3]
        rules.append(hard[0])
    elif bot >= 6 and human <= 2:
        cls, act, note = MALICIOUS_BOT, BLOCK, "Nhiều dấu hiệu tự động, gần như không có bằng chứng người"
        rules.append("BOT_EVIDENCE_STRONG")
    elif bot >= 3 and human < 4 and req.get("challenge_passed"):
        cls, act, note = HUMAN_LIKELY, ALLOW, "Đã vượt thử thách sau khi bị nghi ngờ – cho qua với độ tin cậy thấp, Monitor sẽ yêu cầu xác thực bổ sung"
        rules.append("CHALLENGE_PASSED_AFTER_SUSPECT")
    elif bot >= 3 and human < 4:
        cls, act, note = SUSPECT, CHALLENGE, "Có dấu hiệu tự động chưa được bằng chứng người bù đắp (nghi bot không khai báo)"
        rules.append("BOT_EVIDENCE_UNCOMPENSATED")
    elif bot >= 3 and human >= 4:
        cls, act, note = HUMAN_LIKELY, ALLOW, "Có dấu hiệu tự động nhưng bằng chứng người mạnh hơn"
        rules.append("HUMAN_EVIDENCE_OFFSETS_BOT")
    elif human >= 4:
        cls, act, note = HUMAN_VERIFIED, ALLOW, "Bằng chứng người mạnh, không có dấu hiệu bot"
    else:
        cls, act, note = HUMAN_LIKELY, ALLOW, "Giống người, bằng chứng chưa đủ mạnh"
    return _finish(req, declared, cls, act, bot, human, rules, evid, note, C, ses, extra)


def _finish(req, declared, cls, act, bot, human, rules, evid, note, C, ses, extra=None):
    score = max(0, min(100, 10 * bot - 5 * human))
    if cls == MALICIOUS_BOT:
        score = max(score, 85)
    elif cls == SUSPECT:
        score = max(score, 50)
    out = {"bot_class": cls, "bot_score": score, "action": act, "declared_actor": declared, "bot_points": bot, "human_points": human,
           "rules": rules, "evidence": evid, "note": note,
           "challenge": ("TURNSTILE" if declared == "HUMAN" else "KEY_ROTATION_REVIEW") if act == CHALLENGE else None,
           "observed_automation": bool(bot >= 3) if declared == "HUMAN" else True}
    out.update(extra or {})
    return out


def record_outcome(req: dict, declined: bool):
    """Gọi SAU Monitor: ghi nhận từ chối (để phát hiện bão từ chối/dò thẻ)."""
    if declined:
        store.events_add(f"ab:decl:{req.get('ip') or 'unknown'}", "", keep_seconds=900)


def persist(req: dict, res: dict, action_id=None):
    ses, txn = req.get("session") or {}, req.get("txn") or {}
    try:
        db.execute("INSERT INTO antibot_events(ts,customer_id,source,declared_actor,bot_class,bot_score,action,rules,evidence,ip,device_id,domain,kind,action_id) "
                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (store.now(), txn.get("customer_id"), req.get("source_system") or req.get("agent_id"), res["declared_actor"], res["bot_class"],
                    res["bot_score"], res["action"], json.dumps(res["rules"]), json.dumps(res["evidence"], ensure_ascii=False), req.get("ip"),
                    ses.get("device_id"), txn.get("domain"), txn.get("kind"), action_id))
    except Exception:      # noqa: BLE001  (ghi nhật ký không được làm hỏng luồng)
        pass
