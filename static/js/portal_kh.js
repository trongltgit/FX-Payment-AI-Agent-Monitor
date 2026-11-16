let lastQuoteId = null;
let quoteExpireAt = 0;

function friendlyErr(data, status) {
  if (!data) return "Hệ thống hiện không truy cập được. Vui lòng thử lại sau.";
  if (typeof data === "string" && data.trim().startsWith("<"))
    return "Hệ thống hiện không truy cập được. Vui lòng thử lại sau.";
  if (data.error === "WAITING_CN_SETUP")
    return data.message || "Chưa có báo giá từ chi nhánh. Vui lòng liên hệ chi nhánh.";
  if (data.error === "QUOTE_COOLDOWN")
    return data.message || "Hiện tại hệ thống không cập nhật giá được, xin vui lòng thử lại sau.";
  if (data.error === "SESSION_EXPIRED" || data.error === "AUTHENTICATION_REQUIRED") {
    setTimeout(() => { location.href = data.redirect || "/"; }, 1500);
    return data.message || "Phiên hết hạn. Đăng nhập lại.";
  }
  if (data.error === "BLOCKED") {
    location.href = data.redirect || "/blocked";
    return "Truy cập bị chặn.";
  }
  return data.message || data.error || "Hệ thống hiện không truy cập được. Vui lòng thử lại sau.";
}
async function safeJson(res) {
  const text = await res.text();
  try { return { ok: res.ok, status: res.status, data: JSON.parse(text) }; }
  catch {
    return { ok: false, status: res.status, data: { message: "Hệ thống hiện không truy cập được. Vui lòng thử lại sau." } };
  }
}
async function logout() {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  location.href = "/";
}
function clearPrice(msg) {
  lastQuoteId = null;
  quoteExpireAt = 0;
  document.getElementById("final-price").textContent = "—";
  document.getElementById("price-meta").textContent = "";
  document.getElementById("trade-msg").textContent = "";
  document.getElementById("price-card").style.display = "none";
  document.getElementById("msg").textContent = msg || "";
}
let _csrf = sessionStorage.getItem("csrf_token") || "";
async function ensureCsrf() {
  if (_csrf) return _csrf;
  const r = await safeJson(await fetch("/api/auth/me", { credentials: "same-origin" }));
  if (r.ok && r.data.csrf_token) {
    _csrf = r.data.csrf_token;
    sessionStorage.setItem("csrf_token", _csrf);
  }
  return _csrf;
}
async function apiPost(path, bodyObj) {
  const body = JSON.stringify(bodyObj);
  const csrf = await ensureCsrf();
  const r = await safeJson(await fetch(path, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrf,
    },
    credentials: "same-origin",
    body,
  }));
  return r;
}
async function getQuote() {
  clearPrice("Đang lấy giá...");
  // UI: chiều KH  |  API: chiều NH (đảo ngược)
  // KH Mua → API SELL (NH bán cho KH) → giá cao hơn
  // KH Bán → API BUY  (NH mua từ KH) → giá thấp hơn
  // → đảm bảo cùng thời điểm: giá KH bán < giá KH mua
  const khSide = document.getElementById("side").value;
  const bankSide = khSide === "BUY" ? "SELL" : "BUY";
  const bodyObj = {
    currency: document.getElementById("currency").value,
    side: bankSide,
    amount: Number(document.getElementById("amount").value),
  };
  try {
    const r = await apiPost("/api/transaction/quote", bodyObj);
    if (!r.ok) {
      clearPrice(friendlyErr(r.data, r.status));
      return;
    }
    const q = r.data.quote;
    lastQuoteId = q.quote_id;
    quoteExpireAt = (q.issued_at || Math.floor(Date.now() / 1000)) + (q.valid_for_seconds || 30);
    document.getElementById("msg").textContent = "";
    document.getElementById("price-card").style.display = "block";
    document.getElementById("final-price").textContent = q.price;
    let meta = q.currency + " · Bạn " + (khSide === "BUY" ? "mua" : "bán") +
      " · Hiệu lực " + q.valid_for_seconds + " giây";
    if (q.tgdh && q.tgdh !== q.price) {
      meta += " · TGDH " + q.tgdh;
    }
    document.getElementById("price-meta").textContent = meta;
  } catch (e) {
    clearPrice(e.message || "Hệ thống hiện không truy cập được. Vui lòng thử lại sau.");
  }
}
async function executeTrade() {
  if (!lastQuoteId) {
    document.getElementById("trade-msg").textContent = "Vui lòng xem giá trước.";
    return;
  }
  if (quoteExpireAt && Date.now() / 1000 > quoteExpireAt) {
    clearPrice("Giá đã hết hiệu lực. Vui lòng xem giá lại.");
    return;
  }
  const tm = document.getElementById("trade-msg");
  tm.textContent = "Đang xử lý...";
  try {
    const r = await apiPost("/api/transaction/execute", { quote_id: lastQuoteId });
    if (!r.ok) {
      clearPrice(friendlyErr(r.data, r.status));
      return;
    }
    tm.textContent = "Giao dịch thành công · Mã " + r.data.transaction.transaction_id;
    lastQuoteId = null;
  } catch (e) {
    clearPrice(e.message || "Hệ thống hiện không truy cập được. Vui lòng thử lại sau.");
  }
}
async function loadHistory() {
  const box = document.getElementById("history-box");
  const r = await safeJson(await fetch("/api/transaction/history", { credentials: "same-origin" }));
  if (!r.ok) {
    box.innerHTML = "<p class='error-text'>" + friendlyErr(r.data, r.status) + "</p>";
    return;
  }
  const rows = (r.data.transactions || []).map(
    (t) => "<div class='price-line'><span>" + t.transaction_id + "</span><span>" +
      t.currency + " · " + t.price + "</span></div>"
  );
  box.innerHTML = rows.length ? rows.join("") : "<p class='muted'>Chưa có giao dịch</p>";
}
