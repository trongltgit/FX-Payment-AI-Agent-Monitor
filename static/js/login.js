/** Đăng nhập có chống bot: form-token + Proof-of-Work + honeypot + tín hiệu automation (+ Turnstile, OTP nếu bật). */
(function () {
  "use strict";
  const cfg = window.LOGIN_CFG || {};
  let formToken = cfg.formToken || "";
  let pow = null, powAt = 0, powPromise = null;
  let keys = 0, moves = 0;
  const started = Date.now();

  addEventListener("keydown", () => keys++);
  addEventListener("mousemove", () => moves++, { passive: true });
  addEventListener("touchstart", () => moves++, { passive: true });

  function preparePow() {
    powPromise = (async () => {
      const r = await fetch("/api/auth/challenge", { credentials: "same-origin" });
      const d = await r.json();
      const c = d.challenge;
      const nonce = await AB.solvePow(c.prefix, c.bits);
      pow = { challenge_id: c.challenge_id, nonce: nonce };
      powAt = Date.now();
    })().catch(() => { pow = null; });
    return powPromise;
  }
  preparePow();   // giải ngầm ngay khi mở trang

  const $ = (id) => document.getElementById(id);

  async function doLogin() {
    const err = $("login-error");
    err.textContent = "";
    const username = $("username").value.trim();
    const password = $("password").value;
    if (!username || !password) { err.textContent = "Nhập tên đăng nhập và mật khẩu"; return; }

    err.textContent = "Đang xác minh...";
    await powPromise;
    if (!pow || Date.now() - powAt > 100000) { await preparePow(); }
    if (!pow) { err.textContent = "Không lấy được thử thách bảo mật. Tải lại trang."; return; }

    const body = {
      username, password,
      otp: $("otp") ? $("otp").value.trim() : "",
      form_token: formToken,
      pow: pow,
      website: $("website") ? $("website").value : "",
      hs: { webdriver: navigator.webdriver === true, dwell_ms: Date.now() - started, keys: keys, moves: moves },
    };
    if (window.turnstile && cfg.turnstile) body.turnstile = window.turnstile.getResponse() || "";
    pow = null;   // mỗi challenge chỉ dùng 1 lần

    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (data.form_token) formToken = data.form_token;   // token mới sau mỗi lần thất bại
      if (!res.ok) {
        if (data.error === "MFA_REQUIRED" && $("otp-row")) {
          $("otp-row").style.display = "block"; $("otp").focus();
        }
        err.textContent = data.message || "Đăng nhập thất bại";
        if (data.redirect) setTimeout(() => (location.href = data.redirect), 1200);
        preparePow();
        if (window.turnstile && cfg.turnstile) window.turnstile.reset();
        return;
      }
      const role = (data.user && data.user.role) || "";
      if (cfg.expectedRoles && cfg.expectedRoles[0] && !cfg.expectedRoles.includes(role)) {
        err.textContent = "Tài khoản không thuộc cổng này. Vui lòng chọn đúng cổng.";
        await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin",
                                          headers: { "X-CSRF-Token": data.csrf_token || "" } });
        preparePow();
        return;
      }
      if (data.csrf_token) sessionStorage.setItem("csrf_token", data.csrf_token);
      if (cfg.redirect) location.href = cfg.redirect;
      else if (role === "HQ") location.href = "/portal/hq";
      else if (role === "PNV" || role === "CN_ADMIN") location.href = "/portal/cn";
      else if (role === "CUSTOMER") location.href = "/portal/kh";
      else err.textContent = "Tài khoản không hợp lệ";
    } catch (e) {
      err.textContent = "Lỗi kết nối";
      preparePow();
    }
  }
  window.doLogin = doLogin;
  const pw = $("password");
  if (pw) pw.addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin(); });
})();
