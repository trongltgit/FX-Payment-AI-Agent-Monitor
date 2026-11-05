"""
Bot Defense Engine – chấm điểm HÀNH VI theo tài khoản / IP trên nhiều cửa sổ thời gian.

Vì sao cần: rate limit 1 phút chỉ chặn bot nhanh. Bot "chậm mà đều" (7 lần/phút/tài khoản,
24/7) hoặc bot dùng nhiều tài khoản/IP sẽ lọt. Engine này nhìn các dấu hiệu mà người
thật hiếm khi có:

  Hạn mức cứng (không phụ thuộc điểm):
    - quota theo giờ / theo ngày cho mỗi tài khoản (KH thấp, nhân viên cao)
  Điểm hành vi (cộng dồn, trượt theo thời gian nên tự "nguội" nếu ngừng):
    - metronome      : khoảng cách giữa các lần hỏi giá đều bất thường (CV thấp)
    - enumeration    : quét nhiều tổ hợp (ccy, side, amount) hoặc "đi bộ" số tiền
    - no_execute     : hỏi rất nhiều nhưng không bao giờ giao dịch (đặc trưng cào giá)
    - multi_ip       : 1 tài khoản dùng nhiều IP trong 1 giờ (chia sẻ/xoay proxy)
    - multi_account  : 1 IP đăng nhập nhiều tài khoản KH khác nhau (farm tài khoản)
    - header/ login  : điểm bất thường header + tín hiệu automation lúc đăng nhập

  Hành động theo tổng điểm:
    < CHALLENGE  -> allow
    >= CHALLENGE -> challenge  (client phải giải PoW rồi gửi lại)
    >= THROTTLE  -> throttle   (429 + Retry-After)
    >= BLOCK     -> block      (khóa tài khoản + thu hồi phiên, TSC mở khóa)

Mọi ngưỡng đặt ở PROFILES / THRESHOLDS để vận hành tinh chỉnh theo dữ liệu thật.
"""
import math
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from utils import store

THRESHOLDS = {"challenge": 40, "throttle": 70, "block": 100}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Hạn mức mặc định cho khách hàng online: 30 giá/giờ, 100 giá/ngày (đủ cho nhu cầu thật; chỉnh bằng env).
PROFILES: Dict[str, Dict[str, int]] = {
    "CUSTOMER": {
        "per_min_soft": 8, "per_min_hard": 20,
        "per_hour": _env_int("KH_QUOTE_PER_HOUR", 30), "per_day": _env_int("KH_QUOTE_PER_DAY", 100),
        "distinct_10m": 10, "walk_amounts_10m": 8,
        "no_exec_hour": 20,
    },
    "STAFF": {
        "per_min_soft": 40, "per_min_hard": 80,
        "per_hour": _env_int("STAFF_QUOTE_PER_HOUR", 600), "per_day": _env_int("STAFF_QUOTE_PER_DAY", 3000),
        "distinct_10m": 60, "walk_amounts_10m": 40,
        "no_exec_hour": 10 ** 9,   # nhân viên báo giá nhiều là bình thường
    },
}


def profile_for(role: str) -> Dict[str, int]:
    return PROFILES["CUSTOMER" if (role or "").upper() == "CUSTOMER" else "STAFF"]


@dataclass
class Decision:
    action: str = "allow"          # allow | challenge | throttle | block
    score: int = 0
    reasons: List[str] = field(default_factory=list)
    retry_after: int = 0
    window_hit: str = ""           # "", "soft", "hard" (ngưỡng 60 giây kiểu v1)

    def add(self, pts: int, why: str):
        self.score += pts
        self.reasons.append(f"{why}(+{pts})")


def amount_bucket(amount: float) -> str:
    """Làm tròn 2 chữ số có nghĩa: 1000.00 và 1000.01 cùng nhóm -> hết trò đổi 0,01 để né cooldown."""
    a = float(amount)
    if a <= 0:
        return "0"
    mag = 10 ** (int(math.floor(math.log10(a))) - 1)
    return str(int(round(a / mag) * mag))


# ------------------------------------------------------------------ ghi nhận
def record_quote(user_id: str, role: str, ip: str, currency: str, side: str,
                 amount: float, count: int = 1) -> None:
    payload = f"{currency}|{side}|{amount_bucket(amount)}|{amount}"
    for _ in range(max(1, count)):
        store.events_add(f"q:{user_id}", payload, keep_seconds=86400, maxlen=6000)
    store.events_add(f"uip:{user_id}", ip, keep_seconds=3600)


def record_execute(user_id: str) -> None:
    store.events_add(f"x:{user_id}", "1", keep_seconds=86400)


def record_login(user_id: str, role: str, ip: str) -> None:
    if (role or "").upper() == "CUSTOMER":      # chỉ KH: nhân viên chi nhánh dùng chung IP văn phòng
        store.events_add(f"ipusers:{ip}", user_id, keep_seconds=3600)
    store.events_add(f"uip:{user_id}", ip, keep_seconds=3600)


# --------------------------------------------------------------------- chấm
def _intervals(ts: List[float]) -> List[float]:
    return [b - a for a, b in zip(ts, ts[1:])]


def assess(user_id: str, role: str, ip: str, header_score: int = 0,
           login_risk: int = 0, pending: int = 0) -> Decision:
    """
    Đánh giá TRƯỚC khi phục vụ 1 yêu cầu hỏi giá. `pending` = số lượt sắp tiêu thụ (batch).
    Gọi sau record_quote() thì số đếm đã gồm cả yêu cầu hiện tại.
    """
    p = profile_for(role)
    d = Decision()
    q_all = store.events_recent(f"q:{user_id}", 86400)
    now = store.now()
    q_min = sum(1 for t, _ in q_all if t >= now - 60)
    q_hour = sum(1 for t, _ in q_all if t >= now - 3600)
    q_day = len(q_all)
    q_min, q_hour, q_day = q_min + pending, q_hour + pending, q_day + pending

    # --- hạn mức cứng theo giờ / ngày
    if q_day > p["per_day"]:
        d.action, d.retry_after = "throttle", 3600
        d.reasons.append(f"daily_quota({q_day}>{p['per_day']})")
        d.score = max(d.score, THRESHOLDS["throttle"])
        return d
    if q_hour > p["per_hour"]:
        d.action, d.retry_after = "throttle", 300
        d.reasons.append(f"hourly_quota({q_hour}>{p['per_hour']})")
        d.score = max(d.score, THRESHOLDS["throttle"])
        return d

    # --- ngưỡng 60 giây (giữ ngữ nghĩa v1: soft = buộc đăng nhập lại, hard = khóa)
    if q_min >= p["per_min_hard"]:
        d.window_hit = "hard"
    elif q_min >= p["per_min_soft"]:
        d.window_hit = "soft"

    recent_10m = [(t, pl) for t, pl in q_all if t >= now - 600]

    # --- metronome: khoảng cách đều như đồng hồ
    ts = [t for t, _ in recent_10m]
    if len(ts) >= 9:
        iv = _intervals(ts)
        mean = sum(iv) / len(iv)
        if mean > 0.5:     # chuỗi cực nhanh đã bị rate limit lo
            var = sum((x - mean) ** 2 for x in iv) / len(iv)
            cv = math.sqrt(var) / mean
            if cv < 0.12:
                d.add(40, f"metronome(cv={cv:.2f},n={len(ts)})")

    # --- enumeration
    distinct = {pl.rsplit("|", 1)[0] for _, pl in recent_10m}
    if len(distinct) >= p["distinct_10m"]:
        d.add(30, f"enumeration(distinct={len(distinct)})")
    by_pair: Dict[str, set] = {}
    for _, pl in recent_10m:
        ccy, side, _b, amt = pl.split("|")
        by_pair.setdefault(f"{ccy}|{side}", set()).add(amt)
    walk = max((len(v) for v in by_pair.values()), default=0)
    if walk >= p["walk_amounts_10m"]:
        d.add(25, f"amount_walk(distinct_amounts={walk})")

    # --- hỏi nhiều, không bao giờ giao dịch
    if q_hour >= p["no_exec_hour"] and store.events_count(f"x:{user_id}", 3600) == 0:
        d.add(20, f"no_execute({q_hour} quotes/0 deals)")

    # --- nhiều IP / nhiều tài khoản
    n_ips = store.events_distinct(f"uip:{user_id}", 3600)
    if n_ips >= 4:
        d.add(25, f"multi_ip({n_ips})")
    if (role or "").upper() == "CUSTOMER":
        n_users = store.events_distinct(f"ipusers:{ip}", 3600)
        if n_users >= 4:
            d.add(30, f"multi_account_ip({n_users})")

    if store.events_count(f"cdhit:{user_id}", 600) >= 15:
        d.add(30, "cooldown_spam")

    if header_score >= 25:
        d.add(min(header_score, 30), "header_profile")
    if login_risk:
        d.add(login_risk, "login_signals")

    if store.exists(f"risk:chal:{user_id}"):
        d.add(15, "recent_force_relogin")

    t = THRESHOLDS
    if d.score >= t["block"]:
        d.action = "block"
    elif d.score >= t["throttle"]:
        d.action, d.retry_after = "throttle", 120
    elif d.score >= t["challenge"]:
        d.action = "challenge"
    return d


# --------------------------------------------------------------------- IP
def ip_strike(ip: str, reason: str, weight: int = 2) -> bool:
    """
    Ghi 1 lần vi phạm cho IP *chưa đăng nhập / UA bot / chạm bẫy*. Đủ điểm -> ban tạm.
    Chỉ dùng cho traffic ẩn danh: KHÔNG ban IP vì hành vi của user đã đăng nhập
    (một IP chi nhánh/NAT có thể có hàng chục nhân viên hợp lệ).
    """
    if not ip or ip == "unknown":
        return False
    store.events_add(f"strike:{ip}", f"{reason}|{weight}", keep_seconds=900)
    total = 0
    for _, pl in store.events_recent(f"strike:{ip}", 600):
        try:
            total += int(pl.rsplit("|", 1)[1])
        except (ValueError, IndexError):
            total += 1
    if total >= int(os.environ.get("IP_STRIKE_LIMIT", "10")):
        ban_ip(ip, reason=f"strikes:{reason}", ttl=int(os.environ.get("IP_BAN_SECONDS", "1800")))
        return True
    return False


def ban_ip(ip: str, reason: str = "", ttl: int = 1800) -> None:
    store.set_json(f"ipban:{ip}", {"ip": ip, "reason": reason, "at": int(store.now()), "ttl": ttl}, ttl=ttl)


def is_ip_banned(ip: str) -> bool:
    return bool(ip) and store.exists(f"ipban:{ip}")


def unban_ip(ip: str) -> bool:
    return store.delete(f"ipban:{ip}")


def list_banned_ips() -> List[dict]:
    out = []
    for k in store.keys("ipban:"):
        rec = store.get_json(k)
        if rec:
            rec["remaining"] = store.ttl(k)
            out.append(rec)
    return out
