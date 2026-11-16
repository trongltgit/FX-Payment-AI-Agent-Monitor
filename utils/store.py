"""
State store dùng chung cho toàn bộ lớp chống bot.

  * Có REDIS_URL  -> Redis (đồng bộ giữa mọi worker / instance)
  * Không có      -> RAM trong process (chỉ phù hợp demo, 1 worker)

Tất cả trạng thái an ninh (session, bộ đếm, ban IP, quote đã dùng, nonce, PoW...)
đều đi qua module này để khi bật Redis thì mọi thứ tự đồng bộ.

Thời gian luôn lấy qua store.now() để test có thể "tua" đồng hồ.
"""
import json
import os
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

_lock = threading.RLock()
_mem: Dict[str, Tuple[Optional[float], Any]] = {}
_mem_events: Dict[str, List[Tuple[float, str]]] = {}

_client = None
_client_failed = False
_warned = False


def now() -> float:
    return time.time()


# ------------------------------------------------------------------ backend
def set_client(client) -> None:
    """Dùng cho test (fakeredis) hoặc inject client có sẵn."""
    global _client, _client_failed
    _client = client
    _client_failed = False


def reset_memory() -> None:
    with _lock:
        _mem.clear()
        _mem_events.clear()


def _r():
    global _client, _client_failed, _warned
    if _client is not None:
        return _client or None
    if _client_failed:
        return None
    url = (os.environ.get("REDIS_URL") or "").strip()
    if not url.startswith(("redis://", "rediss://")):
        return None
    try:
        import redis
        c = redis.from_url(url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)
        c.ping()
        _client = c
        return c
    except Exception:
        _client_failed = True
        if not _warned:
            _warned = True
            print("[store] CẢNH BÁO: REDIS_URL cấu hình nhưng không kết nối được -> dùng RAM.")
        return None


def backend() -> str:
    return "redis" if _r() else "memory"


# ---------------------------------------------------------------- key / value
def _mem_get(key: str):
    item = _mem.get(key)
    if not item:
        return None
    exp, val = item
    if exp is not None and exp <= now():
        _mem.pop(key, None)
        return None
    return val


def get(key: str) -> Optional[str]:
    r = _r()
    if r:
        try:
            return r.get(key)
        except Exception:
            pass
    with _lock:
        return _mem_get(key)


def set(key: str, value: str, ttl: Optional[int] = None) -> None:  # noqa: A001
    r = _r()
    if r:
        try:
            r.set(key, value, ex=ttl) if ttl else r.set(key, value)
            return
        except Exception:
            pass
    with _lock:
        _mem[key] = (now() + ttl if ttl else None, value)


def setnx(key: str, value: str = "1", ttl: int = 60) -> bool:
    """Atomic SET-if-not-exists. True nếu vừa tạo (chưa tồn tại)."""
    r = _r()
    if r:
        try:
            return bool(r.set(key, value, nx=True, ex=ttl))
        except Exception:
            pass
    with _lock:
        if _mem_get(key) is not None:
            return False
        _mem[key] = (now() + ttl, value)
        return True


def delete(key: str) -> bool:
    r = _r()
    if r:
        try:
            return bool(r.delete(key))
        except Exception:
            pass
    with _lock:
        return _mem.pop(key, None) is not None


def exists(key: str) -> bool:
    return get(key) is not None


def ttl(key: str) -> int:
    """Số giây còn lại (0 nếu không có / không hết hạn)."""
    r = _r()
    if r:
        try:
            t = r.ttl(key)
            return max(int(t), 0) if t is not None else 0
        except Exception:
            pass
    with _lock:
        item = _mem.get(key)
        if not item or item[0] is None:
            return 0
        return max(int(item[0] - now()), 0)


def incr(key: str, ttl_seconds: Optional[int] = None) -> int:
    """Tăng bộ đếm; đặt hạn lần đầu tiên (nếu có ttl_seconds)."""
    r = _r()
    if r:
        try:
            v = int(r.incr(key))
            if v == 1 and ttl_seconds:
                r.expire(key, ttl_seconds)
            return v
        except Exception:
            pass
    with _lock:
        cur = _mem_get(key)
        if cur is None:
            _mem[key] = (now() + ttl_seconds if ttl_seconds else None, 1)
            return 1
        exp = _mem[key][0]
        _mem[key] = (exp, int(cur) + 1)
        return int(cur) + 1


def get_int(key: str) -> int:
    v = get(key)
    try:
        return int(v) if v is not None else 0
    except (TypeError, ValueError):
        return 0


def get_json(key: str) -> Optional[dict]:
    v = get(key)
    if not v:
        return None
    try:
        return json.loads(v)
    except Exception:
        return None


def set_json(key: str, obj: Any, ttl: Optional[int] = None) -> None:
    set(key, json.dumps(obj, separators=(",", ":")), ttl)


def keys(prefix: str) -> List[str]:
    r = _r()
    if r:
        try:
            return list(r.scan_iter(match=prefix + "*", count=200))
        except Exception:
            pass
    with _lock:
        return [k for k in list(_mem) if k.startswith(prefix) and _mem_get(k) is not None]


# --------------------------------------------------------------------- events
def events_add(key: str, payload: str = "", keep_seconds: int = 86400,
               maxlen: int = 5000, ts: Optional[float] = None) -> None:
    """Ghi 1 sự kiện (thời điểm + payload) vào cửa sổ trượt."""
    t = ts if ts is not None else now()
    r = _r()
    if r:
        try:
            member = f"{t:.6f}|{random.getrandbits(32):08x}|{payload}"
            pipe = r.pipeline()
            pipe.zadd(key, {member: t})
            pipe.zremrangebyscore(key, 0, t - keep_seconds)
            pipe.zremrangebyrank(key, 0, -(maxlen + 1))
            pipe.expire(key, keep_seconds)
            pipe.execute()
            return
        except Exception:
            pass
    with _lock:
        lst = _mem_events.setdefault(key, [])
        lst.append((t, payload))
        cutoff = t - keep_seconds
        if lst and lst[0][0] < cutoff:
            _mem_events[key] = lst = [e for e in lst if e[0] >= cutoff]
        if len(lst) > maxlen:
            del lst[: len(lst) - maxlen]


def events_recent(key: str, window: int) -> List[Tuple[float, str]]:
    """Các sự kiện trong `window` giây gần nhất, cũ -> mới."""
    t = now()
    r = _r()
    if r:
        try:
            raw = r.zrangebyscore(key, t - window, "+inf")
            out = []
            for m in raw:
                ts_s, _, rest = m.split("|", 2)
                out.append((float(ts_s), rest))
            return out
        except Exception:
            pass
    with _lock:
        return [e for e in _mem_events.get(key, []) if e[0] >= t - window]


def events_count(key: str, window: int) -> int:
    return len(events_recent(key, window))


def events_distinct(key: str, window: int) -> int:
    return len({p for _, p in events_recent(key, window)})
