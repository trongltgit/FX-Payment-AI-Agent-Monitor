/* AI Agent Monitor – giao diện dùng chung cho cổng KH / CN / TSC. Mọi chuỗi từ server đều qua esc(). */
(function () {
  "use strict";
  const AM = { role: "", meta: null, cust: "", active: "", timers: {} };
  window.AM = AM;
  const $ = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const n0 = (x) => Number(x || 0).toLocaleString("vi-VN", { maximumFractionDigits: 0 });
  const n2 = (x) => (x == null ? "—" : Number(x).toFixed(2));
  const dt = (t) => (t ? new Date(t * 1000).toLocaleString("vi-VN") : "—");
  const ST = { EXECUTED: "Đã thực hiện", PENDING_KYA: "Chờ xác minh KYA", REVIEW_PENDING: "Chờ CN duyệt", BLOCKED: "Bị chặn", DENIED_BY_CUSTOMER: "KH từ chối",
    REJECTED_BY_STAFF: "NV từ chối", EXPIRED: "Hết hạn KYA", FAILED: "Thất bại", PENDING_EXEC: "Đang thực hiện", ACTIVE: "Hoạt động", PENDING: "Chờ duyệt",
    PAUSED: "KH tạm dừng", SUSPENDED: "Bị đình chỉ", REVOKED: "Đã thu hồi", REJECTED: "Bị từ chối", FROZEN: "Đã khóa tạm" };
  const KIND = { FX_TRADE: "Lệnh FX", TRANSFER: "Chuyển tiền", ONLINE_PURCHASE: "Mua sắm online", CARD_PAYMENT: "Thanh toán thẻ" };
  const badge = (v, txt) => `<span class="badge b-${esc(v)}">${esc(txt || ST[v] || v)}</span>`;

  async function api(path, body, method) {
    const opt = { credentials: "same-origin", headers: { "Content-Type": "application/json" } };
    if (body !== undefined) { opt.method = method || "POST"; opt.body = JSON.stringify(body); }
    let r, d = {};
    try { r = await fetch(path, opt); } catch (e) { return { ok: false, status: 0, data: { message: "Không kết nối được máy chủ." } }; }
    try { d = await r.json(); } catch (e) { d = { message: "Phản hồi không hợp lệ." }; }
    if (r.status === 401 && d.error === "AUTHENTICATION_REQUIRED") location.href = "/";
    return { ok: r.ok, status: r.status, data: d };
  }
  function toast(msg, isErr) {
    const t = document.createElement("div"); t.className = "toast" + (isErr ? " err" : ""); t.textContent = msg;
    document.body.appendChild(t); setTimeout(() => t.remove(), 4200);
  }
  const fail = (r) => toast((r.data && (r.data.message || r.data.error)) || "Lỗi", true);
  AM.api = api; AM.esc = esc; AM.toast = toast;

  /* ---------------- tabs ---------------- */
  AM.initTabs = function (defs, first) {
    const bar = $("am-tabs");
    bar.innerHTML = defs.map((t) => `<button class="tab-btn" data-act="tab" data-id="${t.id}">${esc(t.label)}<span class="dot" id="dot-${t.id}" style="display:none"></span></button>`).join("");
    AM.defs = defs; AM.show(first || defs[0].id);
  };
  AM.show = function (id) {
    AM.active = id;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.id === id));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.toggle("active", p.id === "tab-" + id));
    Object.values(AM.timers).forEach(clearInterval); AM.timers = {};
    const d = AM.defs.find((x) => x.id === id);
    if (d && d.load) d.load();
  };
  function setDot(id, n) { const e = $("dot-" + id); if (e) { e.style.display = n ? "" : "none"; e.textContent = n; } }

  /* ---------------- chọn khách hàng ---------------- */
  function custSelect(panelId, rerender) {
    if (AM.role === "CUSTOMER") return "";
    const opts = AM.meta.customers.map((c) => `<option value="${esc(c.customer_id)}" ${c.customer_id === AM.cust ? "selected" : ""}>${esc(c.customer_id)} – ${esc(c.name)} (${esc(c.segment)}, ${esc(c.branch_id)})</option>`).join("");
    return `<div class="toolbar"><label class="muted small">Khách hàng</label><select data-act="cust" data-panel="${panelId}" class="full-select" style="width:auto;margin:0">${opts}</select></div>`;
  }
  AM.reload = function () { const d = AM.defs.find((x) => x.id === AM.active); if (d && d.load) d.load(); };

  /* ---------------- Monitor: tổng quan + lịch sử ---------------- */
  function desc(a) {
    if (a.domain === "FX") return `${esc(a.side)} ${esc(a.pair)} · ${n0(a.amount_usd)} USD · ${a.leverage || 1}x`;
    let s = KIND[a.kind] || a.kind;
    s += ` · ${n0(a.amount_vnd)} đ`;
    if (a.beneficiary) s += ` → ${esc(a.beneficiary)}`;
    if (a.merchant) s += ` · ${esc(a.merchant)} ${esc(a.country || "")} MCC ${esc(a.mcc || "")}`;
    return s;
  }
  function chart(series) {
    if (!series.length) return "<p class='muted small'>Chưa có dữ liệu trong kỳ.</p>";
    const mx = Math.max(...series.map((s) => s.ALLOW + s.KYA + s.REVIEW + s.BLOCK), 1);
    return `<div class="chart">${series.map((s) => `<div class="col" title="${esc(s.day)}: ALLOW ${s.ALLOW}, KYA ${s.KYA}, REVIEW ${s.REVIEW}, BLOCK ${s.BLOCK}">` +
      ["ALLOW", "KYA", "REVIEW", "BLOCK"].map((k) => `<div class="seg s-${k}" style="height:${(s[k] / mx) * 110}px"></div>`).join("") + "</div>").join("")}</div>
      <div class="legend"><span><i class="s-ALLOW"></i>ALLOW</span><span><i class="s-KYA"></i>KYA</span><span><i class="s-REVIEW"></i>REVIEW</span><span><i class="s-BLOCK"></i>BLOCK</span></div>`;
  }
  const TRIG = { AMOUNT_OVER_KYA: "Vượt ngưỡng KYA", NEW_BENEFICIARY: "Người nhận mới", FIRST_ONLINE: "Lần đầu online", DORMANT_WAKE: "Ngủ đông", BALANCE_DRAIN: "Rút gần hết số dư",
    AGENT_PROBATION: "Agent thử việc", NO_3DS: "Không 3DS", NEW_COUNTRY: "Quốc gia mới", HIGH_RISK_COUNTRY: "Quốc gia rủi ro", HIGH_RISK_MCC: "MCC rủi ro",
    LEVERAGE_SPIKE: "Đòn bẩy đột biến", CARD_TESTING: "Dò thẻ", PCI_VIOLATION: "Vi phạm PCI" };

  AM.renderMonitor = async function (domain, panelId) {
    const el = $(panelId);
    el.innerHTML = custSelect(panelId) + "<p class='muted'>Đang tải…</p>";
    const q = AM.role === "CUSTOMER" ? "" : "&customer_id=" + encodeURIComponent(AM.cust);
    const scopeAll = AM.role !== "CUSTOMER" && AM.showAll;
    const [o, h] = await Promise.all([
      api(`/api/agent/overview?domain=${domain}&days=90${scopeAll ? "" : q}`),
      api(`/api/agent/actions?domain=${domain}&limit=60${scopeAll ? "" : q}`)]);
    if (!o.ok) { el.innerHTML = custSelect(panelId) + `<p class="error-text">${esc(o.data.message)}</p>`; return; }
    const d = o.data, u = d.unit;
    const dec = d.by_decision || {};
    const kp = (l, v, cls) => `<div class="kpi"><div class="v ${cls || ""}">${v}</div><div class="l">${l}</div></div>`;
    let html = custSelect(panelId) + (AM.role !== "CUSTOMER" ? `<label class="small muted"><input type="checkbox" data-act="scope" ${AM.showAll ? "checked" : ""}> Xem toàn bộ phạm vi (mọi KH của tôi)</label>` : "") + `
      <div class="am-grid">
        ${kp("Tổng giao dịch (90 ngày)", n0(d.total))}${kp("ALLOW", n0(dec.ALLOW || 0))}${kp("KYA", n0(dec.KYA || 0))}${kp("REVIEW", n0(dec.REVIEW || 0))}${kp("BLOCK", n0(dec.BLOCK || 0))}
        ${kp("Giá trị đã thực hiện (" + u + ")", n0(d.volume_executed))}${kp("Giá trị bị chặn/từ chối (" + u + ")", n0(d.volume_stopped))}
        ${kp("Đang chờ KYA", n0(d.pending_kya))}${kp("Chờ CN duyệt", n0(d.review_queue))}</div>
      <h3>Quyết định theo ngày</h3>${chart(d.series)}`;
    if (AM.role !== "CUSTOMER") {
      const mx = Math.max(...d.risk_hist, 1);
      html += `<div class="row-flex" style="align-items:flex-start;gap:2rem"><div style="flex:1;min-width:240px"><h3>Phân bố điểm rủi ro</h3>` +
        d.risk_hist.map((v, i) => `<div class="hbar"><span style="width:4.5rem">${(i * 0.2).toFixed(1)}–${((i + 1) * 0.2).toFixed(1)}</span><div class="bar" style="width:${(v / mx) * 140}px"></div>${v}</div>`).join("") +
        `</div><div style="flex:1;min-width:240px"><h3>Tín hiệu kích hoạt KYA nhiều nhất</h3>` +
        (d.top_triggers.length ? d.top_triggers.map((t) => `<div class="hbar"><span style="width:10rem">${esc(TRIG[t[0]] || t[0])}</span><div class="bar" style="width:${t[1] * 8}px"></div>${t[1]}</div>`).join("") : "<p class='muted small'>Không có.</p>") + `</div></div>`;
      if (d.watchlist.length) html += `<h3>Khách đang theo dõi (suspicion)</h3>` + d.watchlist.map((w) => `<span class="badge ${w.watchlist ? "b-BLOCK" : "b-KYA"}" style="margin-right:.4rem">${esc(w.customer_id)} ${Number(w.suspicion).toFixed(2)}</span>`).join("");
    }
    html += `<h3>Lịch sử giao dịch (60 gần nhất)</h3>` + actionsTable(h.data.actions || []);
    el.innerHTML = html;
  };
  function actionsTable(rows) {
    if (!rows.length) return "<p class='muted'>Chưa có giao dịch.</p>";
    const staff = AM.role !== "CUSTOMER";
    return `<div class="table-wrap"><table class="data"><thead><tr><th>Thời gian</th>${staff ? "<th>KH</th>" : ""}<th>Agent</th><th>Giao dịch</th><th>QĐ</th><th>Trạng thái</th>${staff ? "<th>Rủi ro</th>" : ""}</tr></thead><tbody>` +
      rows.map((a) => `<tr class="row" data-act="detail" data-id="${a.id}"><td>${dt(a.ts)}</td>${staff ? `<td>${esc(a.customer_id)}</td>` : ""}<td>${esc(a.agent_id)}</td><td>${desc(a)}</td><td>${badge(a.decision)}</td><td>${badge(a.status)}</td>${staff ? `<td>${n2(a.final_risk)}</td>` : ""}</tr><tr id="d-${a.id}" style="display:none"><td colspan="7"></td></tr>`).join("") + "</tbody></table></div>";
  }
  async function toggleDetail(id) {
    const row = $("d-" + id); if (!row) return;
    if (row.style.display !== "none") { row.style.display = "none"; return; }
    const r = await api("/api/agent/actions/" + id); if (!r.ok) return fail(r);
    const a = r.data.action, staff = AM.role !== "CUSTOMER";
    let h = `<div class="detail"><b>${esc(a.reason_public || "")}</b>`;
    if (a.hard_reason) h += `<div class="error-text">Hard policy: ${esc(a.hard_reason)}</div>`;
    if ((a.triggers || []).length) h += `<div>Yêu cầu KYA vì: ${a.triggers.map((t) => "<span class='badge b-KYA'>" + esc(t) + "</span>").join(" ")}</div>`;
    if (staff) {
      h += `<div class="small muted" style="margin-top:.3rem">Điểm: ML ${n2(a.anomaly)} · Hành vi ${n2(a.behavior)} · Velocity ${n2(a.velocity)} · <b>Tổng ${n2(a.final_risk)}</b></div>`;
      if ((a.reasons || []).length) h += `<pre>• ${a.reasons.map(esc).join("\n• ")}</pre>`;
      if (a.llm) h += `<div class="small" style="margin-top:.4rem"><b>LLM Critic (${esc(a.llm.source)}):</b> ${esc(a.llm.explanation)}</div>`;
    }
    if (a.kya) h += `<div class="small muted">KYA ${esc(a.kya.id)}: ${esc(a.kya.status)} ${a.kya.method ? "· " + esc(a.kya.method) : ""}</div>`;
    if (a.reviewer) h += `<div class="small muted">Duyệt bởi ${esc(a.reviewer)}: ${esc(a.review_note || "")}</div>`;
    row.firstElementChild.innerHTML = h + "</div>"; row.style.display = "";
  }

  /* ---------------- Test Lab ---------------- */
  AM.renderLab = async function (panelId) {
    const el = $(panelId);
    const [s, ag] = await Promise.all([api("/api/agent/lab/scenarios"), api("/api/agent/agents" + (AM.role === "CUSTOMER" ? "" : "?customer_id=" + encodeURIComponent(AM.cust)))]);
    if (!s.ok) { el.innerHTML = `<p class="error-text">${esc(s.data.message)}</p>`; return; }
    const hints = { "PAY-06": "CUST004", "PAY-07": "CUST003", "PAY-15": "CUST004" };
    const row = (x) => `<tr><td><b>${x.id}</b></td><td>${esc(x.title)}<div class="muted small">${esc(x.desc)}${hints[x.id] ? " <b>(khách gợi ý: " + hints[x.id] + ")</b>" : ""}</div></td><td>${badge(x.expected === "MIXED" ? "REVIEW" : x.expected.split("/")[0], x.expected === "MIXED" ? "Tăng dần" : x.expected)}</td><td><button data-act="lab" data-id="${x.id}">Chạy</button></td></tr>`;
    const tbl = (dom) => `<div class="table-wrap"><table class="data"><thead><tr><th>Mã</th><th>Kịch bản</th><th>Kỳ vọng</th><th></th></tr></thead><tbody>${s.data.scenarios.filter((x) => x.domain === dom).map(row).join("")}</tbody></table></div>`;
    const agents = (ag.data.agents || []).map((a) => `<option value="${esc(a.agent_id)}">${esc(a.agent_id)} (${esc(a.status)})</option>`).join("");
    el.innerHTML = custSelect(panelId) + `<div class="note">Test Lab chạy giao dịch qua <b>đúng pipeline thật</b>: Hard Policy → Feature → Isolation Forest → LLM Critic → Quyết định. Giao dịch được ghi vào CSDL, hiện trong tab Monitor; giao dịch KYA chờ khách xác nhận.
      <br><button class="secondary" data-act="topup">Nạp số dư demo 1 tỷ cho KH đang chọn</button></div>
      <h3>Kịch bản FX</h3>${tbl("FX")}<h3>Kịch bản Thanh toán / Thẻ</h3>${tbl("PAY")}
      <h3>Kết quả</h3><div id="lab-out" class="result-box"><span class="muted">Chọn “Chạy” để xem kết quả từng bước.</span></div>
      <h3>Giao dịch tự soạn (như một Agent)</h3>
      <div class="row-flex"><select id="lc-agent">${agents}<option value="agent-ghost">agent-ghost (chưa đăng ký)</option></select>
      <select id="lc-tpl" data-act="tpl"><option value="fx">Mẫu FX</option><option value="tr">Mẫu chuyển tiền</option><option value="card">Mẫu mua sắm online</option></select>
      <input id="lc-hour" class="mini-in" placeholder="Giờ giả lập 0-23"></div>
      <textarea id="lc-json" rows="8" style="width:100%;margin-top:.5rem;background:var(--bg);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:.5rem;font-family:ui-monospace,monospace"></textarea>
      <button data-act="custom">Gửi giao dịch</button><div id="lc-out" class="result-box"></div>`;
    tpl();
  };
  const TPL = {
    fx: { domain: "FX", kind: "FX_TRADE", pair: "USDVND", side: "BUY", notional_usd: 10000, leverage: 2 },
    tr: { domain: "PAY", kind: "TRANSFER", amount_vnd: 5000000, beneficiary_account: "1234567890" },
    card: { domain: "PAY", kind: "ONLINE_PURCHASE", amount_vnd: 2000000, card_token: "(dán token thẻ từ tab Thẻ)", merchant_id: "M300", mcc: "5411", country: "VN", three_ds: true } };
  function tpl() { const t = $("lc-tpl"), j = $("lc-json"); if (t && j) j.value = JSON.stringify(TPL[t.value], null, 2); }
  function stepsHtml(steps) {
    return `<div class="table-wrap"><table class="data"><thead><tr><th>#</th><th>Yêu cầu</th><th>Quyết định</th><th>Điểm (ML/HV/VEL → tổng)</th><th>Lý do</th></tr></thead><tbody>` +
      steps.map((s, i) => `<tr><td>${i + 1}</td><td class="small">${esc(JSON.stringify(s.request))}</td><td>${badge(s.decision)}<br>${badge(s.status)}</td>
      <td class="small">${s.risk == null ? "—" : `${n2(s.anomaly)} / ${n2(s.behavior)} / ${n2(s.velocity)} → <b>${n2(s.risk)}</b>`}</td>
      <td class="small">${esc(s.reason)}${s.kya_id ? `<br><span class="badge b-KYA">Chờ KYA ${esc(s.kya_id)}</span>` : ""}${s.llm ? `<br><i>LLM: ${esc(s.llm.explanation)}</i>` : ""}</td></tr>`).join("") + "</tbody></table></div>";
  }
  async function runLab(id) {
    const out = $("lab-out"); out.innerHTML = "Đang chạy…";
    const r = await api("/api/agent/lab/run", { scenario: id, customer_id: AM.cust });
    if (!r.ok) { out.innerHTML = `<span class="error-text">${esc(r.data.message)}</span>`; return; }
    out.innerHTML = `<b>${esc(id)}</b> · Agent <code>${esc(r.data.agent_id)}</code> · KH ${esc(r.data.customer_id)}${r.data.note ? `<div class="note warn-note">${esc(r.data.note)}</div>` : ""}` + stepsHtml(r.data.steps) +
      (r.data.steps.some((s) => s.kya_id) ? `<div class="note warn-note">Có giao dịch chờ KYA: khách mở tab <b>Authenticator &amp; KYA</b> (hoặc trang <a href="/authenticator" target="_blank" rel="noopener">/authenticator</a>) để duyệt/từ chối.</div>` : "");
    refreshBadges();
  }
  async function customTx() {
    let payload; try { payload = JSON.parse($("lc-json").value); } catch (e) { return toast("JSON không hợp lệ", true); }
    const body = { customer_id: AM.cust, agent_id: $("lc-agent").value, payload };
    if ($("lc-hour").value !== "") body.sim_hour = Number($("lc-hour").value);
    const r = await api("/api/agent/lab/custom", body); const out = $("lc-out");
    if (!r.ok) { out.innerHTML = `<span class="error-text">${esc(r.data.message)}</span>`; return; }
    const a = r.data.result;
    out.innerHTML = `${badge(a.decision)} ${badge(a.status)} <div>${esc(a.reason_public)}</div>` + (a.hard_reason ? `<div class="error-text">${esc(a.hard_reason)}</div>` : "") +
      ((a.triggers || []).length ? `<div class="small">KYA vì: ${a.triggers.map(esc).join("; ")}</div>` : "") + (a.final_risk != null ? `<div class="small muted">Rủi ro ${n2(a.final_risk)} (ML ${n2(a.anomaly)} · HV ${n2(a.behavior)} · VEL ${n2(a.velocity)})</div>` : "");
    refreshBadges();
  }

  /* ---------------- Khách hàng ---------------- */
  AM.renderMyAgents = async function () {
    const el = $("tab-agents");
    const [r, m] = [await api("/api/agent/agents"), AM.meta];
    const lim = (a) => Object.entries(a.limits || {}).map(([dom, v]) => `<div class="small"><b>${dom}</b>: ${Object.entries(v).map(([k, x]) => `${esc(m.labels[k] || k)}=${Array.isArray(x) ? esc(x.join(",")) : n0(x)}`).join(" · ") || "theo trần TSC/CN"}</div>`).join("");
    const cards = (r.data.agents || []).map((a) => `<div class="card"><div class="row-flex"><b>${esc(a.name)}</b> <code>${esc(a.agent_id)}</code> ${badge(a.status)} ${a.domains.map((d) => `<span class="badge b-VISA">${d === "FX" ? "FX" : "Thanh toán"}</span>`).join("")}</div>
      <div class="small muted">Đăng ký ${dt(a.requested_at)} · Duyệt bởi ${esc(a.approved_by || "—")} · Hiệu lực đến ${dt(a.valid_until)} · Thử việc còn ${a.probation_left} GD · KH từ chối KYA ${a.denied_count} lần${a.status_note ? " · " + esc(a.status_note) : ""}${a.reject_reason ? " · Lý do từ chối: " + esc(a.reject_reason) : ""}</div>${lim(a)}
      <div class="row-flex" style="margin-top:.5rem">${a.status === "ACTIVE" ? `<button class="secondary" data-act="ag-status" data-id="${esc(a.agent_id)}" data-v="PAUSED">Tạm dừng</button>` : ""}${a.status === "PAUSED" ? `<button data-act="ag-status" data-id="${esc(a.agent_id)}" data-v="ACTIVE">Khôi phục</button>` : ""}
      ${["ACTIVE", "PAUSED", "SUSPENDED"].includes(a.status) ? `<button class="secondary" data-act="ag-lower" data-id="${esc(a.agent_id)}">Hạ hạn mức</button><button data-act="ag-key" data-id="${esc(a.agent_id)}">${a.has_key ? "Cấp lại API key" : "Cấp API key"}</button><button class="secondary" data-act="ag-status" data-id="${esc(a.agent_id)}" data-v="REVOKED">Thu hồi</button>` : ""}</div></div>`).join("");
    el.innerHTML = `<div class="card"><h2>Đăng ký AI Agent với ngân hàng</h2>
      <div class="note warn-note">Pháp lý: khách hàng <b>bắt buộc đăng ký</b> mọi AI Agent được phép thực hiện giao dịch. Agent chưa được chi nhánh duyệt sẽ bị chặn hoàn toàn. Cần đã đăng ký <b>Authenticator</b> (tab bên cạnh) để xác minh KYA.</div>
      <div class="form-col"><label>Tên Agent</label><input id="rg-name" placeholder="VD: Robot FX của tôi"><label>Mục đích sử dụng</label><input id="rg-purpose" placeholder="VD: giao dịch ngoại tệ theo chiến lược…">
      <label>Nghiệp vụ</label><div class="row-flex"><label><input type="checkbox" id="rg-fx" checked> FX Trading</label><label><input type="checkbox" id="rg-pay" checked> Thanh toán (chuyển tiền, mua sắm online, thẻ)</label></div>
      <label>Hạn mức đề nghị (chi nhánh sẽ kẹp theo trần TSC)</label>
      <div class="row-flex"><input id="rg-fx1" class="mini-in" placeholder="FX / lệnh (USD)"><input id="rg-fx2" class="mini-in" placeholder="FX / ngày (USD)"><input id="rg-p1" class="mini-in" placeholder="Chuyển / lần (VND)"><input id="rg-p2" class="mini-in" placeholder="Chuyển / ngày (VND)"></div>
      <label>Điều khoản pháp lý (v${esc(m.consent.version)})</label><div class="consent">${esc(m.consent.text)}</div>
      <label><input type="checkbox" id="rg-consent"> Tôi đã đọc và đồng ý toàn bộ điều khoản trên</label>
      <label>Mã OTP Authenticator (6 số)</label><input id="rg-otp" inputmode="numeric" maxlength="6" class="mini-in"><button data-act="register">Gửi hồ sơ đăng ký</button></div></div>
      <h2>Agent của tôi</h2><div id="key-out"></div>${cards || "<p class='muted'>Chưa có Agent.</p>"}
      <div class="note">Agent gọi: <code>POST /agent-api/v1/monitor/action</code> với <code>Authorization: Bearer &lt;API key&gt;</code>. Chỉ gửi <b>token thẻ</b>, tuyệt đối không gửi số thẻ/CVV (bị chặn theo PCI-DSS).</div>`;
  };
  async function register() {
    const num = (id) => ($(id).value ? Number($(id).value) : undefined);
    const doms = [$("rg-fx").checked ? "FX" : null, $("rg-pay").checked ? "PAY" : null].filter(Boolean);
    const req = { FX: {}, PAY: {} };
    if (num("rg-fx1")) req.FX.per_order_usd = num("rg-fx1"); if (num("rg-fx2")) req.FX.daily_usd = num("rg-fx2");
    if (num("rg-p1")) req.PAY.transfer_per_txn = num("rg-p1"); if (num("rg-p2")) req.PAY.transfer_daily = num("rg-p2");
    const r = await api("/api/agent/me/agents/register", { name: $("rg-name").value, purpose: $("rg-purpose").value, domains: doms, requested_limits: req, consent: $("rg-consent").checked, totp: $("rg-otp").value });
    if (!r.ok) return fail(r); toast(r.data.message); AM.renderMyAgents();
  }

  AM.renderAuth = async function () {
    const el = $("tab-auth");
    const [a, p] = await Promise.all([api("/api/agent/me/authenticator"), api("/api/agent/me/kya/pending")]);
    const list = p.data.pending || [];
    setDot("auth", list.length);
    el.innerHTML = `<div class="card"><h2>Ứng dụng Authenticator</h2>
      <p>Trạng thái: ${a.data.enrolled ? badge("ACTIVE", "Đã đăng ký TOTP") : badge("PENDING", "Chưa đăng ký")} ${a.data.device_paired ? badge("ACTIVE", "Đã ghép thiết bị: " + esc(a.data.device_label)) : badge("EXPIRED", "Chưa ghép thiết bị")}
      ${a.data.demo_totp_now ? `<span class="small muted"> · Mã OTP hiện tại (chỉ hiện ở demo): <b>${esc(a.data.demo_totp_now)}</b></span>` : ""}</p>
      <div class="row-flex"><button data-act="pairing">Tạo mã ghép nối / secret TOTP</button>${a.data.device_paired ? `<button class="secondary" data-act="unpair">Gỡ thiết bị</button>` : ""}
      <a href="/authenticator" target="_blank" rel="noopener">Mở Authenticator (giả lập điện thoại) ↗</a></div><div id="pair-out"></div>
      <div class="note">Hai cách xác minh KYA: <b>(1) PUSH</b> – ghép thiết bị bằng mã 8 số, duyệt bằng PIN; <b>(2) TOTP</b> – nhập mã 6 số từ Google/Microsoft Authenticator (quét/nhập secret ở trên).</div></div>
      <h2>Giao dịch chờ xác minh (KYA)</h2>
      ${list.length ? list.map((k) => `<div class="card kya-card"><div class="row-flex"><b>${esc(KIND[k.kind] || k.kind)}</b> ${badge("PENDING_KYA")} <span class="small muted">Agent ${esc(k.agent_id)} · còn ${k.expires_in}s</span></div>
        <div>${k.domain === "FX" ? `${esc(k.side)} ${esc(k.pair)} · ${n0(k.amount_usd)} USD · ${k.leverage}x` : `${n0(k.amount_vnd)} đ${k.beneficiary ? " → " + esc(k.beneficiary) : ""}${k.merchant ? " · " + esc(k.merchant) + " " + esc(k.country || "") : ""}`}</div>
        <div class="small">${(k.triggers || []).map((t) => `<span class="badge b-KYA">${esc(t[1])}</span>`).join(" ")}</div>
        <div class="row-flex" style="margin-top:.5rem"><input class="mini-in" id="otp-${esc(k.kya_id)}" placeholder="Mã OTP 6 số" inputmode="numeric" maxlength="6"><button data-act="kya-ok" data-id="${esc(k.kya_id)}">Duyệt</button><button class="secondary" data-act="kya-no" data-id="${esc(k.kya_id)}">Từ chối</button></div></div>`).join("") : "<p class='muted'>Không có giao dịch nào đang chờ.</p>"}`;
    AM.timers.kya = setInterval(async () => { const q = await api("/api/agent/me/kya/pending"); if (q.ok) { setDot("auth", q.data.pending.length); if (AM.active === "auth" && q.data.pending.length !== list.length && !document.activeElement.id.startsWith("otp-")) AM.renderAuth(); } }, 5000);
  };

  AM.renderCards = async function () {
    const el = $("tab-cards");
    const [c, b] = await Promise.all([api("/api/agent/me/cards"), api("/api/agent/me/beneficiaries")]);
    el.innerHTML = `<div class="card"><h2>Thẻ Visa / Mastercard</h2>
      <div class="note">Tuân thủ PCI-DSS: hệ thống <b>không lưu số thẻ đầy đủ</b> (chỉ BIN + 4 số cuối + token), <b>không bao giờ nhận CVV</b>. Agent chỉ dùng <code>token</code>. Visa bắt đầu bằng 4; Mastercard 51–55 hoặc 2221–2720 (16 số); kiểm tra Luhn.</div>
      <div class="table-wrap"><table class="data"><thead><tr><th>Thẻ</th><th>Mạng</th><th>Hạn mức/GD</th><th>Hạn mức/ngày</th><th>Online</th><th>Quốc tế</th><th>Token cho Agent</th><th></th></tr></thead><tbody>` +
      (c.data.cards || []).map((x) => `<tr><td>${esc(x.masked)}<div class="small muted">${esc(x.holder)} · ${esc(x.expiry)}</div></td><td>${badge(x.network)}</td><td>${n0(x.per_txn_limit)}</td><td>${n0(x.daily_limit)}</td>
        <td><input type="checkbox" data-act="card-tog" data-id="${esc(x.card_id)}" data-f="cnp_enabled" ${x.cnp_enabled ? "checked" : ""}></td><td><input type="checkbox" data-act="card-tog" data-id="${esc(x.card_id)}" data-f="intl_enabled" ${x.intl_enabled ? "checked" : ""}></td>
        <td><code class="small">${esc(x.token)}</code></td><td>${badge(x.status)}<br><button class="secondary" data-act="card-freeze" data-id="${esc(x.card_id)}" data-v="${x.status === "ACTIVE" ? "FROZEN" : "ACTIVE"}">${x.status === "ACTIVE" ? "Khóa tạm" : "Mở khóa"}</button></td></tr>`).join("") + `</tbody></table></div>
      <h3>Thêm thẻ (dùng số thẻ TEST)</h3><div class="row-flex"><input id="cd-pan" placeholder="Số thẻ test, VD 4242424242424242" style="min-width:16rem" autocomplete="off"><button class="secondary" data-act="card-check">Kiểm tra số thẻ</button></div>
      <div class="row-flex"><input id="cd-holder" placeholder="Tên in trên thẻ" class="mini-in"><input id="cd-m" placeholder="MM" class="mini-in" style="width:4rem"><input id="cd-y" placeholder="YYYY" class="mini-in" style="width:5rem"><input id="cd-t" placeholder="Hạn mức/GD" class="mini-in"><input id="cd-d" placeholder="Hạn mức/ngày" class="mini-in">
      <label><input type="checkbox" id="cd-cnp" checked> Online</label><label><input type="checkbox" id="cd-intl"> Quốc tế</label><button data-act="card-add">Thêm thẻ</button></div><div id="cd-out" class="small"></div></div>
      <div class="card"><h2>Người nhận tin cậy</h2><p class="hint">Chuyển tiền cho người nhận chưa từng giao dịch và chưa nằm trong danh sách tin cậy sẽ cần KYA khi vượt ngưỡng.</p>
      <div class="row-flex"><input id="bn-acc" placeholder="Số tài khoản" class="mini-in"><input id="bn-bank" placeholder="Ngân hàng" class="mini-in"><button data-act="benef-add">Thêm</button></div>
      ${(b.data.beneficiaries || []).map((x) => `<div class="small">${esc(x.account)} · ${esc(x.bank)}</div>`).join("")}</div>`;
  };

  /* ---------------- Chi nhánh ---------------- */
  AM.renderRegs = async function () {
    const el = $("tab-regs");
    const r = await api("/api/agent/agents");
    const isAdmin = AM.role === "CN_ADMIN" || AM.role === "HQ";
    const rows = r.data.agents || [];
    setDot("regs", rows.filter((a) => a.status === "PENDING").length);
    const limInputs = (a) => a.domains.map((d) => (d === "FX" ? [["per_order_usd", "FX/lệnh USD"], ["daily_usd", "FX/ngày USD"], ["max_leverage", "Đòn bẩy"]] : [["transfer_per_txn", "Chuyển/lần"], ["transfer_daily", "Chuyển/ngày"], ["card_per_txn", "Thẻ/GD"], ["kya_above", "KYA từ"]]).map(([k, l]) => `<input class="mini-in" data-lim="${d}.${k}" data-for="${esc(a.agent_id)}" placeholder="${l}" value="${esc(((a.requested_limits || {})[d] || {})[k] || "")}">`).join("")).join("");
    el.innerHTML = custSelect("tab-regs") + `<div class="note">CN_ADMIN duyệt hồ sơ và đặt hạn mức Agent. Hạn mức luôn bị <b>kẹp ≤ trần TSC</b> (và ≤ hạn mức CN của CIF).</div>` +
      rows.filter((a) => AM.role === "CUSTOMER" || true).map((a) => `<div class="card"><div class="row-flex"><b>${esc(a.name)}</b> <code>${esc(a.agent_id)}</code> ${badge(a.status)} <span class="muted small">KH ${esc(a.customer_id)} · ${a.domains.join("+")}</span></div>
        <div class="small muted">Mục đích: ${esc(a.purpose || "—")} · Đồng ý điều khoản v${esc(a.consent_version)} lúc ${dt(a.consent_at)} · Đăng ký ${dt(a.requested_at)} · Duyệt: ${esc(a.approved_by || "—")}</div>
        ${a.status === "PENDING" && isAdmin ? `<div class="row-flex" style="margin-top:.5rem">${limInputs(a)}<button data-act="reg-ok" data-id="${esc(a.agent_id)}">Duyệt</button><button class="secondary" data-act="reg-no" data-id="${esc(a.agent_id)}">Từ chối</button></div>` : ""}
        ${["ACTIVE", "PAUSED", "SUSPENDED"].includes(a.status) && isAdmin ? `<div class="row-flex" style="margin-top:.5rem">${a.status === "ACTIVE" ? `<button class="secondary" data-act="reg-st" data-id="${esc(a.agent_id)}" data-v="SUSPENDED">Đình chỉ</button>` : `<button data-act="reg-st" data-id="${esc(a.agent_id)}" data-v="ACTIVE">Khôi phục</button>`}<button class="secondary" data-act="reg-st" data-id="${esc(a.agent_id)}" data-v="REVOKED">Thu hồi</button></div>` : ""}</div>`).join("") || "<p class='muted'>Không có hồ sơ.</p>";
  };
  AM.renderLimits = async function () {
    const el = $("tab-limits"); const out = [];
    for (const dom of ["FX", "PAY"]) {
      const r = await api(`/api/agent/cn/limits?customer_id=${encodeURIComponent(AM.cust)}&domain=${dom}`);
      if (!r.ok) { el.innerHTML = custSelect("tab-limits") + `<p class="error-text">${esc(r.data.message)}</p>`; return; }
      const d = r.data, keys = AM.meta.num_keys[dom];
      out.push(`<div class="card"><h2>${dom === "FX" ? "FX Trading" : "Thanh toán"} – ${esc(d.segment)}</h2><div class="lim-grid"><div class="h">Chỉ tiêu</div><div class="h">Trần TSC</div><div class="h">Hạn mức CN (nhập)</div><div class="h">Hiệu lực</div>` +
        keys.map((k) => `<div>${esc(AM.meta.labels[k] || k)}</div><div>${n0(d.tsc_cap[k])}</div><div><input data-cnlim="${dom}.${k}" value="${d.cn_override[k] != null ? d.cn_override[k] : ""}" placeholder="≤ ${n0(d.tsc_cap[k])}"></div><div><b>${n0(d.effective[k])}</b></div>`).join("") +
        `</div>${AM.role !== "PNV" && AM.role !== "STAFF" ? `<button data-act="lim-save" data-dom="${dom}" style="margin-top:.6rem">Lưu hạn mức ${dom}</button>` : "<p class='muted small'>Chỉ Admin CN/TSC chỉnh sửa.</p>"}</div>`);
    }
    el.innerHTML = custSelect("tab-limits") + out.join("");
  };
  AM.renderQueue = async function () {
    const el = $("tab-queue"); const r = await api("/api/agent/cn/review-queue");
    const q = r.data.queue || []; setDot("queue", q.length);
    el.innerHTML = `<div class="note">Giao dịch có rủi ro cao (REVIEW) được giữ lại; nhân viên phụ trách CIF duyệt hoặc từ chối. Số tiền được <b>giữ chỗ</b> trong số dư khả dụng.</div>` +
      (q.length ? q.map((a) => `<div class="card"><div class="row-flex"><b>${esc(a.customer_id)}</b> ${badge("REVIEW_PENDING")} <span class="muted small">${dt(a.ts)} · Agent ${esc(a.agent_id)}</span></div><div>${desc(a)}</div>
        <div class="small">Rủi ro <b>${n2(a.final_risk)}</b> (ML ${n2(a.anomaly)} · HV ${n2(a.behavior)} · VEL ${n2(a.velocity)})</div><pre class="small muted" style="white-space:pre-wrap">• ${(a.reasons || []).map(esc).join("\n• ")}</pre>
        ${a.llm ? `<div class="small"><b>LLM:</b> ${esc(a.llm.explanation)}</div>` : ""}<div class="row-flex" style="margin-top:.4rem"><input id="rv-${a.id}" placeholder="Ghi chú" style="min-width:12rem"><button data-act="rv-ok" data-id="${a.id}">Duyệt &amp; thực hiện</button><button class="secondary" data-act="rv-no" data-id="${a.id}">Từ chối</button></div></div>`).join("") : "<p class='muted'>Hàng chờ trống.</p>");
  };
  AM.renderAdminCards = async function () {
    const el = $("tab-acards"); const r = await api("/api/agent/cn/cards");
    const adm = AM.role === "CN_ADMIN" || AM.role === "HQ";
    el.innerHTML = `<div class="note">Chỉ hiển thị số thẻ đã che (BIN + 4 số cuối). Token và số đầy đủ không bao giờ xuất hiện ở đây.</div><div class="table-wrap"><table class="data"><thead><tr><th>KH</th><th>Thẻ</th><th>Mạng</th><th>GD</th><th>Ngày</th><th>Online</th><th>QT</th><th>Trạng thái</th>${adm ? "<th></th>" : ""}</tr></thead><tbody>` +
      (r.data.cards || []).map((x) => `<tr><td>${esc(x.customer_id)}</td><td>${esc(x.masked)}<div class="small muted">${esc(x.expiry)}</div></td><td>${badge(x.network)}</td><td>${n0(x.per_txn_limit)}</td><td>${n0(x.daily_limit)}</td><td>${x.cnp_enabled ? "✓" : "—"}</td><td>${x.intl_enabled ? "✓" : "—"}</td><td>${badge(x.status)}</td>
      ${adm ? `<td><button class="secondary" data-act="acard" data-id="${esc(x.card_id)}" data-v="${x.status === "ACTIVE" ? "FROZEN" : "ACTIVE"}">${x.status === "ACTIVE" ? "Khóa tạm" : "Mở"}</button> <button class="secondary" data-act="acard" data-id="${esc(x.card_id)}" data-v="BLOCKED">Khóa hẳn</button></td>` : ""}</tr>`).join("") + "</tbody></table></div>";
  };
  AM.renderProfile = async function () {
    const el = $("tab-profile"); const r = await api("/api/agent/profile?customer_id=" + encodeURIComponent(AM.cust));
    if (!r.ok) { el.innerHTML = custSelect("tab-profile") + `<p class="error-text">${esc(r.data.message)}</p>`; return; }
    const p = r.data.profile;
    const dom = (d, x) => `<div class="card"><h3>${d === "FX" ? "FX" : "Thanh toán"} – thói quen</h3><div class="small">Số giao dịch: <b>${x.n}</b> · Trung bình: <b>${n0(x.avg)}</b> · Lớn nhất: ${n0(x.max)} · Giờ quen: ${esc(x.typical_hours.join(", ") || "—")}<br>` +
      (d === "FX" ? `Cặp: ${esc(x.pairs.join(", "))} · Đòn bẩy TB ${x.avg_leverage}` : `Người nhận: ${x.beneficiaries} · Merchant: ${x.merchants} · Quốc gia: ${esc(x.countries.join(", "))} · Theo loại: ${esc(JSON.stringify(x.by_kind))}`) + `</div></div>`;
    el.innerHTML = custSelect("tab-profile") + `<div class="am-grid"><div class="kpi"><div class="v">${esc(p.name)}</div><div class="l">${esc(p.segment)} · ${esc(p.branch_id)}</div></div><div class="kpi"><div class="v">${n0(p.balance_vnd)}</div><div class="l">Số dư thanh toán (VND)</div></div><div class="kpi"><div class="v">${n0(p.available_vnd)}</div><div class="l">Khả dụng (trừ phần đang giữ)</div></div>
      <div class="kpi"><div class="v ${p.watchlist ? "error-text" : ""}">${n2(p.suspicion)}</div><div class="l">Suspicion ${p.watchlist ? "· WATCHLIST" : ""}</div></div><div class="kpi"><div class="v">${p.online_history.is_first_time ? "CHƯA" : p.online_history.count}</div><div class="l">Giao dịch online/agent từng có</div></div><div class="kpi"><div class="v">${p.days_since_last_txn == null ? "—" : p.days_since_last_txn}</div><div class="l">Ngày từ giao dịch gần nhất</div></div></div>
      ${dom("FX", p.domains.FX)}${dom("PAY", p.domains.PAY)}${AM.role !== "PNV" && AM.role !== "STAFF" ? `<button class="secondary" data-act="clearflag">Xóa cờ theo dõi (suspicion)</button>` : ""}`;
  };

  /* ---------------- TSC ---------------- */
  AM.renderPolicy = async function (dom) {
    const el = $("tab-pol" + dom.toLowerCase()); const r = await api("/api/agent/hq/policy/" + dom);
    const P = r.data.policy, L = r.data.labels, segs = Object.keys(P.segments), keys = AM.meta.num_keys[dom];
    const g = P.global; const gnum = ["kya_threshold", "review_threshold", "block_threshold", "kya_ttl_seconds", "max_pending_kya", "probation_actions", "dormant_days", "balance_drain_pct"].concat(dom === "PAY" ? ["cnp_3ds_above_vnd"] : ["usd_vnd"]);
    const glist = dom === "PAY" ? ["blocked_mcc", "high_risk_mcc", "blocked_countries", "high_risk_countries", "blocked_accounts"] : [];
    el.innerHTML = `<div class="note">Trần TSC áp dụng theo phân khúc. Chi nhánh/KH chỉ được đặt hạn mức <b>thấp hơn hoặc bằng</b>. Ngưỡng điểm: KYA &lt; REVIEW &lt; BLOCK.</div>
      <div class="card"><h2>Ngưỡng & tham số chung ${dom}</h2><div class="lim-grid" style="grid-template-columns:1.4fr 1fr">${gnum.map((k) => `<div>${esc(k)}</div><input data-pg="${k}" value="${esc(g[k])}">`).join("")}${glist.map((k) => `<div>${esc(k)}</div><input data-pgl="${k}" value="${esc((g[k] || []).join(","))}">`).join("")}</div></div>
      <div class="card"><h2>Trần theo phân khúc</h2><div class="lim-grid" style="grid-template-columns:1.6fr repeat(${segs.length},1fr)"><div class="h">Chỉ tiêu</div>${segs.map((s) => `<div class="h">${esc(s)}</div>`).join("")}` +
      keys.map((k) => `<div>${esc(L[k] || k)}</div>` + segs.map((s) => `<input data-ps="${s}.${k}" value="${esc(P.segments[s][k])}">`).join("")).join("") +
      (dom === "FX" ? `<div>Cặp được phép</div>` + segs.map((s) => `<input data-psl="${s}" value="${esc((P.segments[s].allowed_pairs || []).join(","))}">`).join("") : "") + `</div></div>
      <button data-act="pol-save" data-dom="${dom}">Lưu chính sách ${dom}</button>`;
  };
  AM.renderKill = async function () {
    const el = $("tab-kill"); const [k, a] = await Promise.all([api("/api/agent/hq/killswitch"), api("/api/agent/agents")]);
    const ag = a.data.agents || [];
    el.innerHTML = `<div class="card"><h2>Kill-switch toàn hệ thống</h2><p>Trạng thái: ${k.data.on ? badge("BLOCK", "ĐANG BẬT – mọi giao dịch Agent bị chặn") : badge("ACTIVE", "Bình thường")} <span class="small muted">${esc(k.data.reason || "")} ${esc(k.data.by || "")}</span></p>
      <div class="row-flex"><input id="ks-reason" placeholder="Lý do" style="min-width:14rem"><button data-act="ks" data-v="1">Bật kill-switch</button><button class="secondary" data-act="ks" data-v="0">Tắt</button></div></div>
      <div class="card"><h2>Toàn bộ Agent đã đăng ký (${ag.length})</h2><div class="table-wrap"><table class="data"><thead><tr><th>Agent</th><th>KH</th><th>Nghiệp vụ</th><th>Trạng thái</th><th>KYA bị từ chối</th><th></th></tr></thead><tbody>` +
      ag.map((x) => `<tr><td>${esc(x.name)}<div class="small muted">${esc(x.agent_id)}</div></td><td>${esc(x.customer_id)}</td><td>${x.domains.join("+")}</td><td>${badge(x.status)}</td><td>${x.denied_count}</td><td>${["ACTIVE", "PAUSED"].includes(x.status) ? `<button class="secondary" data-act="reg-st" data-id="${esc(x.agent_id)}" data-v="SUSPENDED">Đình chỉ</button>` : ""}${x.status === "SUSPENDED" ? `<button data-act="reg-st" data-id="${esc(x.agent_id)}" data-v="ACTIVE">Khôi phục</button>` : ""}</td></tr>`).join("") + "</tbody></table></div></div>";
  };
  AM.renderModel = async function () {
    const el = $("tab-model"); const r = await api("/api/agent/hq/model");
    const m = r.data.models, l = r.data.llm;
    el.innerHTML = `<div class="am-grid">${["FX", "PAY"].map((d) => `<div class="kpi"><div class="l">Isolation Forest ${d}</div><div class="v">${m[d].n_samples || "—"}</div><div class="l">mẫu · huấn luyện ${dt(m[d].trained_at)}<br>Bắt ${m[d].detected_injected_pct}% bất thường chèn vào · báo nhầm ${m[d].flagged_normal_pct}%<br>${(m[d].features || []).length} đặc trưng</div></div>`).join("")}
      <div class="kpi"><div class="l">LLM Critic</div><div class="v" style="font-size:1rem">${esc(l.provider)}</div><div class="l">${esc(l.model)} · chế độ ${esc(l.mode)}<br>${esc(l.note)}</div></div></div>
      <div class="note">Mô hình ML học trên dữ liệu tổng hợp bằng <b>chính hàm feature</b> của hệ thống. Production: huấn luyện lại bằng lịch sử thật đã gắn nhãn. LLM chỉ được <b>nâng</b> mức rủi ro, không bao giờ hạ hay ghi đè hard policy.</div>
      <div class="row-flex"><button data-act="retrain">Huấn luyện lại 2 mô hình</button><button class="secondary" data-act="reseed">Đặt lại dữ liệu demo</button></div>`;
  };

  /* ---------------- badge đếm ---------------- */
  async function refreshBadges() {
    if (AM.role === "CUSTOMER") { const p = await api("/api/agent/me/kya/pending"); if (p.ok) setDot("auth", p.data.pending.length); }
    else if (AM.role !== "HQ" || true) { const q = await api("/api/agent/cn/review-queue"); if (q.ok) setDot("queue", q.data.queue.length); }
  }

  /* ---------------- sự kiện ---------------- */
  document.addEventListener("change", (e) => {
    const t = e.target, a = t.dataset && t.dataset.act;
    if (a === "cust") { AM.cust = t.value; sessionStorage.setItem("am_cust", AM.cust); AM.reload(); }
    if (a === "tpl") tpl();
    if (a === "scope") { AM.showAll = t.checked; AM.reload(); }
    if (a === "card-tog") api("/api/agent/me/cards/" + t.dataset.id, { [t.dataset.f]: t.checked }).then((r) => { if (!r.ok) fail(r); });
  });
  document.addEventListener("click", async (e) => {
    const t = e.target.closest("[data-act]"); if (!t || t.tagName === "SELECT" || t.type === "checkbox") return;
    const a = t.dataset.act, id = t.dataset.id, v = t.dataset.v; let r;
    switch (a) {
      case "tab": return AM.show(id);
      case "detail": return toggleDetail(id);
      case "lab": return runLab(id);
      case "custom": return customTx();
      case "topup": r = await api("/api/agent/lab/topup", { customer_id: AM.cust, amount: 1e9 }); return r.ok ? toast("Đã nạp số dư demo") : fail(r);
      case "register": return register();
      case "ag-status": if (v === "REVOKED" && !confirm("Thu hồi Agent vĩnh viễn?")) return; r = await api(`/api/agent/me/agents/${id}/status`, { status: v }); r.ok ? AM.renderMyAgents() : fail(r); return;
      case "ag-lower": { const dom = prompt("Nghiệp vụ (FX hoặc PAY)?", "FX"); if (!dom) return; const k = prompt("Chỉ tiêu (VD per_order_usd, daily_usd, transfer_per_txn)", dom.toUpperCase() === "FX" ? "per_order_usd" : "transfer_per_txn"); const val = prompt("Giá trị mới (chỉ được HẠ)"); if (!k || !val) return; r = await api(`/api/agent/me/agents/${id}/limits`, { domain: dom.toUpperCase(), values: { [k]: Number(val) } }); r.ok ? (toast("Đã hạ hạn mức"), AM.renderMyAgents()) : fail(r); return; }
      case "ag-key": { const otp = prompt("Nhập mã OTP Authenticator để cấp API key"); if (!otp) return; r = await api(`/api/agent/me/agents/${id}/api-key`, { totp: otp }); if (!r.ok) return fail(r); $("key-out").innerHTML = `<div class="note warn-note">${esc(r.data.warning)}</div><div class="key-box">${esc(r.data.api_key)}</div>`; return; }
      case "pairing": r = await api("/api/agent/me/authenticator/start", {}); if (!r.ok) return fail(r); $("pair-out").innerHTML = `<div class="note warn-note">Mã ghép nối (hết hạn sau 10 phút): <b style="font-size:1.3rem;letter-spacing:.2rem">${esc(r.data.pairing_code)}</b><br>Secret TOTP (nhập vào Google/Microsoft Authenticator): <code>${esc(r.data.totp_secret)}</code><br><span class="small">URI: ${esc(r.data.otpauth_uri)}</span></div>`; return;
      case "unpair": await api("/api/agent/me/authenticator/unpair", {}); return AM.renderAuth();
      case "kya-ok": r = await api(`/api/agent/me/kya/${id}/approve`, { code: $("otp-" + id).value }); r.ok ? (toast("Đã duyệt – giao dịch " + r.data.result.status), AM.renderAuth()) : fail(r); return;
      case "kya-no": r = await api(`/api/agent/me/kya/${id}/deny`, {}); r.ok ? (toast("Đã từ chối giao dịch"), AM.renderAuth()) : fail(r); return;
      case "card-check": r = await api("/api/agent/cards/validate", { pan: $("cd-pan").value }); $("cd-out").innerHTML = r.data.valid ? `<span class="badge b-ACTIVE">Hợp lệ</span> ${esc(r.data.network)} · ${esc(r.data.masked)}` : `<span class="error-text">${esc(r.data.message)}</span>`; return;
      case "card-add": r = await api("/api/agent/me/cards", { pan: $("cd-pan").value, holder: $("cd-holder").value, exp_month: $("cd-m").value, exp_year: $("cd-y").value, per_txn_limit: $("cd-t").value, daily_limit: $("cd-d").value, cnp_enabled: $("cd-cnp").checked, intl_enabled: $("cd-intl").checked }); r.ok ? (toast("Đã thêm thẻ – số thẻ đã được token hóa và hủy"), AM.renderCards()) : fail(r); return;
      case "card-freeze": r = await api("/api/agent/me/cards/" + id, { status: v }); r.ok ? AM.renderCards() : fail(r); return;
      case "benef-add": r = await api("/api/agent/me/beneficiaries", { account: $("bn-acc").value, bank: $("bn-bank").value }); r.ok ? AM.renderCards() : fail(r); return;
      case "reg-ok": { const lim = { FX: {}, PAY: {} }; document.querySelectorAll(`[data-for="${id}"]`).forEach((i) => { if (i.value) { const [d, k] = i.dataset.lim.split("."); lim[d][k] = Number(i.value); } }); r = await api(`/api/agent/cn/registrations/${id}/approve`, { limits: lim }); r.ok ? (toast("Đã duyệt Agent"), AM.renderRegs()) : fail(r); return; }
      case "reg-no": { const why = prompt("Lý do từ chối?"); if (why == null) return; r = await api(`/api/agent/cn/registrations/${id}/reject`, { reason: why }); r.ok ? AM.renderRegs() : fail(r); return; }
      case "reg-st": r = await api(`/api/agent/cn/agents/${id}/status`, { status: v, note: "Thao tác từ cổng quản trị" }); r.ok ? AM.reload() : fail(r); return;
      case "lim-save": { const values = {}; document.querySelectorAll(`[data-cnlim^="${t.dataset.dom}."]`).forEach((i) => { if (i.value) values[i.dataset.cnlim.split(".")[1]] = Number(i.value); }); r = await api("/api/agent/cn/limits", { customer_id: AM.cust, domain: t.dataset.dom, values }); r.ok ? (toast("Đã lưu hạn mức"), AM.renderLimits()) : fail(r); return; }
      case "rv-ok": case "rv-no": r = await api("/api/agent/cn/review/" + id, { approve: a === "rv-ok", note: $("rv-" + id).value }); r.ok ? (toast("Đã xử lý"), AM.renderQueue()) : fail(r); return;
      case "acard": r = await api(`/api/agent/cn/cards/${id}/status`, { status: v }); r.ok ? AM.renderAdminCards() : fail(r); return;
      case "clearflag": r = await api("/api/agent/cn/flags/clear", { customer_id: AM.cust }); r.ok ? AM.renderProfile() : fail(r); return;
      case "pol-save": { const dom = t.dataset.dom, body = { global: {}, segments: {} };
        document.querySelectorAll("[data-pg]").forEach((i) => { body.global[i.dataset.pg] = Number(i.value); });
        document.querySelectorAll("[data-pgl]").forEach((i) => { body.global[i.dataset.pgl] = i.value.split(",").map((x) => x.trim()).filter(Boolean); });
        document.querySelectorAll("[data-ps]").forEach((i) => { const [s, k] = i.dataset.ps.split("."); (body.segments[s] = body.segments[s] || {})[k] = Number(i.value); });
        document.querySelectorAll("[data-psl]").forEach((i) => { (body.segments[i.dataset.psl] = body.segments[i.dataset.psl] || {}).allowed_pairs = i.value.split(",").map((x) => x.trim()).filter(Boolean); });
        r = await api("/api/agent/hq/policy/" + dom, body); r.ok ? toast("Đã lưu chính sách " + dom) : fail(r); return; }
      case "ks": r = await api("/api/agent/hq/killswitch", { on: v === "1", reason: $("ks-reason").value }); r.ok ? AM.renderKill() : fail(r); return;
      case "retrain": toast("Đang huấn luyện…"); r = await api("/api/agent/hq/model/retrain", {}); r.ok ? (toast("Xong"), AM.renderModel()) : fail(r); return;
      case "reseed": if (!confirm("Xóa toàn bộ dữ liệu AI Agent demo và tạo lại?")) return; r = await api("/api/agent/hq/reseed", {}); r.ok ? (toast("Đã đặt lại"), AM.renderModel()) : fail(r); return;
    }
  });

  /* ---------------- khởi động ---------------- */
  AM.start = async function (role, defs, first) {
    AM.role = role;
    const m = await api("/api/agent/meta"); if (!m.ok) { fail(m); return; }
    AM.meta = m.data; AM.cust = sessionStorage.getItem("am_cust") || (m.data.customers[0] || {}).customer_id || "";
    if (!m.data.customers.some((c) => c.customer_id === AM.cust)) AM.cust = (m.data.customers[0] || {}).customer_id || "";
    AM.initTabs(defs, first); refreshBadges(); setInterval(refreshBadges, 15000);
  };
})();
