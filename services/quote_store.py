"""
Quote store phía server.

v1 giữ quote trong cookie-session: người dùng đọc được, và việc "execute" phụ thuộc
dữ liệu nằm ở client. v2: quote nằm ở server, gắn với (user, phiên). Client chỉ giữ quote_id.
  * execute kiểm tra: đúng chủ sở hữu, đúng phiên, chưa hết hạn, chưa bị CN interrupt
  * sau đó claim nguyên tử (SETNX) -> mỗi quote chỉ execute đúng 1 lần
"""
from typing import Optional

from utils import store


def save(quote_id: str, payload: dict, valid_seconds: int) -> None:
    store.set_json(f"quote:{quote_id}", payload, ttl=int(valid_seconds) + 120)


def load(quote_id: str) -> Optional[dict]:
    if not quote_id:
        return None
    return store.get_json(f"quote:{quote_id}")
