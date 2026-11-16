"""
Server-side session (thay cho cookie-session mặc định của Flask).

Vì sao cần:
  * Cookie-session của Flask chỉ được KÝ, không được mã hóa và KHÔNG thể thu hồi.
    Bot giữ cookie cũ vẫn dùng được sau khi bị "force relogin" hoặc bị khóa.
  * Ở đây cookie chỉ chứa 1 mã sid ngẫu nhiên (đã ký). Dữ liệu phiên (role,
    CIF được phép, csrf_token, fingerprint...) nằm trong store (Redis/RAM).
  * Thu hồi phiên = xóa bản ghi -> cookie cũ lập tức vô dụng.

Phiên ẩn danh (chưa đăng nhập) KHÔNG được lưu -> bot không thể spam tạo bản ghi.
"""
import secrets
from datetime import timedelta
from typing import Optional

from flask import Flask, request as flask_request
from flask.sessions import SessionInterface, SessionMixin
from itsdangerous import BadSignature, URLSafeSerializer
from werkzeug.datastructures import CallbackDict

from utils import store

IDLE_TTL = 1800          # 30 phút không hoạt động
ABSOLUTE_TTL = 8 * 3600  # tối đa 8 giờ kể từ lúc đăng nhập


class ServerSession(CallbackDict, SessionMixin):
    def __init__(self, initial=None, sid: Optional[str] = None, new: bool = False):
        def on_update(self_):
            self_.modified = True

        super().__init__(initial or {}, on_update)
        self.sid = sid or secrets.token_urlsafe(32)
        self.new = new
        self.modified = False
        self.rotate_requested = False

    def rotate(self):
        """Cấp sid mới (chống session fixation) – gọi ngay sau đăng nhập."""
        self.rotate_requested = True
        self.modified = True


class ServerSessionInterface(SessionInterface):
    cookie_name = "ab_sid"
    key_prefix = "sess:"

    def _serializer(self, app: Flask):
        return URLSafeSerializer(app.secret_key, salt="ab-sid")

    # ------------------------------------------------------------------ open
    def open_session(self, app: Flask, request):
        raw = request.cookies.get(self.cookie_name)
        if raw:
            try:
                sid = self._serializer(app).loads(raw)
            except BadSignature:
                sid = None
            if sid:
                data = store.get_json(self.key_prefix + sid)
                if data:
                    created = data.get("_created", 0)
                    if store.now() - created <= ABSOLUTE_TTL:
                        return ServerSession(data, sid=sid)
                    store.delete(self.key_prefix + sid)
        return ServerSession(new=True)

    # ------------------------------------------------------------------ save
    def save_session(self, app: Flask, session: ServerSession, response):
        domain = self.get_cookie_domain(app)
        path = self.get_cookie_path(app)
        key = self.key_prefix + session.sid
        logged_in = bool(session.get("user_id"))

        if session.rotate_requested:
            store.delete(key)
            session.sid = secrets.token_urlsafe(32)
            key = self.key_prefix + session.sid
            session.modified = True

        if not logged_in:
            # Phiên rỗng / ẩn danh: xóa bản ghi cũ (nếu có) và xóa cookie.
            if session.modified or not session.new:
                store.delete(key)
            if flask_request.cookies.get(self.cookie_name):
                response.delete_cookie(self.cookie_name, domain=domain, path=path)
            return

        if not session.get("_created"):
            session["_created"] = int(store.now())
        data = dict(session)
        store.set_json(key, data, ttl=IDLE_TTL)  # sliding idle timeout

        # Danh sách sid theo user -> cho phép thu hồi toàn bộ phiên của 1 user
        if session.new or session.modified:
            store.events_add(f"usess:{data['user_id']}", session.sid, keep_seconds=ABSOLUTE_TTL, maxlen=50)

        response.set_cookie(
            self.cookie_name,
            self._serializer(app).dumps(session.sid),
            max_age=None,                      # cookie phiên (đóng trình duyệt là mất)
            httponly=True,
            secure=app.config.get("SESSION_COOKIE_SECURE", True),
            samesite=app.config.get("SESSION_COOKIE_SAMESITE", "Lax"),
            domain=domain,
            path=path,
        )
        response.vary.add("Cookie")


# ----------------------------------------------------------------- thu hồi
def revoke_user(user_id: str, except_sid: Optional[str] = None) -> int:
    """Xóa mọi phiên đang mở của user. Trả về số phiên đã thu hồi."""
    n = 0
    for _, sid in store.events_recent(f"usess:{user_id}", ABSOLUTE_TTL):
        if sid and sid != except_sid and store.delete(ServerSessionInterface.key_prefix + sid):
            n += 1
    return n


def active_sessions(user_id: str) -> int:
    seen = set()
    for _, sid in store.events_recent(f"usess:{user_id}", ABSOLUTE_TTL):
        if sid and store.exists(ServerSessionInterface.key_prefix + sid):
            seen.add(sid)
    return len(seen)
