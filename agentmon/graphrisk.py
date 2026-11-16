"""PHÁT HIỆN VÒNG GIAN LẬN BẰNG ĐỒ THỊ LIÊN KẾT: khách hàng nối với nhau qua THIẾT BỊ, NGƯỜI NHẬN và IP dùng chung (7 ngày).
ring_size = số khách KHÁC trong thành phần liên thông (tối đa 2 bước) – dấu hiệu trang trại tài khoản, mạng mule, lừa đảo có tổ chức.
Cảnh báo: gia đình/doanh nghiệp dùng chung thiết bị hợp lệ cũng tạo liên kết → chỉ là tín hiệu, không chặn cứng."""
from agentmon import db

WINDOW = 7 * 86400
CAP = 25


def _q(sql, args):
    return db.query(sql, args)


def ring_size(cid: str, device: str | None, beneficiary: str | None, ip: str | None, now: float) -> int:
    seen_c = {cid}
    attrs = {"dev": {device} if device else set(), "ben": {beneficiary} if beneficiary else set(), "ip": {ip} if ip else set()}
    since = now - WINDOW
    for _ in range(2):                                        # 2 bước lan truyền
        new_c = set()
        if attrs["dev"]:
            ph = ",".join("?" * len(attrs["dev"]))
            new_c |= {r["customer_id"] for r in _q(f"SELECT DISTINCT customer_id FROM actions WHERE device_id IN ({ph}) AND ts>? AND sim!=2", (*attrs["dev"], since))}
            new_c |= {r["customer_id"] for r in _q(f"SELECT DISTINCT customer_id FROM antibot_events WHERE device_id IN ({ph}) AND ts>?", (*attrs["dev"], since))}
        if attrs["ben"]:
            ph = ",".join("?" * len(attrs["ben"]))
            new_c |= {r["customer_id"] for r in _q(f"SELECT DISTINCT customer_id FROM actions WHERE beneficiary IN ({ph}) AND ts>? AND sim!=2", (*attrs["ben"], since))}
        if attrs["ip"]:
            ph = ",".join("?" * len(attrs["ip"]))
            new_c |= {r["customer_id"] for r in _q(f"SELECT DISTINCT customer_id FROM antibot_events WHERE ip IN ({ph}) AND ts>?", (*attrs["ip"], since))}
        new_c = {c for c in new_c if c} - seen_c
        if not new_c:
            break
        seen_c |= new_c
        if len(seen_c) > CAP:
            break
        ph = ",".join("?" * len(new_c))
        for r in _q(f"SELECT device_id d, beneficiary b FROM actions WHERE customer_id IN ({ph}) AND ts>? AND sim!=2", (*new_c, since)):
            if r["d"]:
                attrs["dev"].add(r["d"])
            if r["b"]:
                attrs["ben"].add(r["b"])
    return min(len(seen_c) - 1, CAP)
