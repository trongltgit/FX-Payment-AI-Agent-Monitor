(function () {
  "use strict";
  const KEY = "am_device_token";
  let token = localStorage.getItem(KEY) || "";
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const vnd = (n) => Number(n || 0).toLocaleString("vi-VN") + " đ";

  async function call(path, opt) {
    opt = opt || {};
    opt.headers = Object.assign({ "Content-Type": "application/json" }, token ? { Authorization: "Bearer " + token } : {});
    const r = await fetch(path, opt);
    let d = {};
    try { d = await r.json(); } catch (e) { /* */ }
    return { ok: r.ok, status: r.status, data: d };
  }
  window.pair = async function () {
    const r = await call("/authapp/pair", { method: "POST", body: JSON.stringify({ pairing_code: $("pc").value.trim(), pin: $("pp").value.trim(), label: navigator.platform || "Thiết bị" }) });
    if (!r.ok) { $("pm").textContent = r.data.message || "Ghép thất bại"; return; }
    token = r.data.device_token; localStorage.setItem(KEY, token); show();
  };
  window.unlink = function () { localStorage.removeItem(KEY); token = ""; location.reload(); };
  function describe(p) {
    if (p.domain === "FX") return `<b>FX ${esc(p.side)} ${esc(p.pair)}</b><br>Giá trị: ${Number(p.amount_usd).toLocaleString("en-US")} USD · đòn bẩy ${esc(p.leverage)}x`;
    const k = { TRANSFER: "Chuyển tiền", ONLINE_PURCHASE: "Mua sắm online", CARD_PAYMENT: "Thanh toán thẻ" }[p.kind] || p.kind;
    return `<b>${k}</b><br>${vnd(p.amount_vnd)}` + (p.beneficiary ? `<br>Người nhận: ${esc(p.beneficiary)}` : "") + (p.merchant ? `<br>Merchant: ${esc(p.merchant)} (${esc(p.country)})` : "");
  }
  async function decide(id, approve) {
    let pin = "";
    if (approve) { pin = prompt("Nhập PIN thiết bị để DUYỆT"); if (!pin) return; }
    const r = await call("/authapp/decide", { method: "POST", body: JSON.stringify({ kya_id: id, approve, pin }) });
    if (!r.ok) alert(r.data.message || "Lỗi"); poll();
  }
  window.decideKya = decide;
  async function poll() {
    if (!token) return;
    const r = await call("/authapp/pending");
    if (r.status === 401) { localStorage.removeItem(KEY); token = ""; $("main").style.display = "none"; $("pair-card").style.display = ""; return; }
    $("who").textContent = "Khách hàng " + (r.data.customer_id || ""); $("dev").textContent = "Thiết bị: " + (r.data.device || "");
    const list = r.data.pending || [];
    $("list").innerHTML = list.length ? list.map((p) => `
      <div class="card kya-card"><div class="muted small">Agent ${esc(p.agent_id)} · còn ${p.expires_in}s</div>
      <p>${describe(p)}</p>
      <ul class="small">${(p.triggers || []).map((t) => "<li>" + esc(t[1] || t) + "</li>").join("")}</ul>
      <div class="form-row"><button onclick="decideKya('${esc(p.kya_id)}',true)">Duyệt</button>
      <button class="secondary" onclick="decideKya('${esc(p.kya_id)}',false)">Từ chối</button></div></div>`).join("")
      : "<p class='muted center'>Không có giao dịch nào cần xác minh.</p>";
  }
  function show() { $("pair-card").style.display = "none"; $("main").style.display = ""; poll(); setInterval(poll, 3000); }
  if (token) show();
})();
