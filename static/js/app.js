/** Anti-Bot Pro – 3 roles HQ / CN / Customer */

let currentRole = null;

async function callApi(url) {
  const res = await fetch(url, { credentials: "same-origin" });
  return { status: res.status, data: await res.json() };
}

async function doLogin() {
  const el = document.getElementById("login-result");
  el.textContent = "Đang đăng nhập...";
  const username = document.getElementById("username").value;
  const password = document.getElementById("password").value;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ username, password }),
    });
    const data = await res.json();
    el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
    if (res.ok) {
      if (data.csrf_token) {
        sessionStorage.setItem("csrf_token", data.csrf_token);
        _csrf = data.csrf_token;
      }
      currentRole = data.user.role;
      document.getElementById("login-status").innerHTML =
        "Đã đăng nhập: <strong>" + data.user.name + "</strong> (" + data.user.role + ")";
      document.getElementById("hq-panel").style.display =
        data.user.role === "HQ" ? "block" : "none";
    }
  } catch (err) {
    el.textContent = "Lỗi: " + err.message;
  }
}

async function doLogout() {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  currentRole = null;
  document.getElementById("login-status").textContent = "Chưa đăng nhập";
  document.getElementById("hq-panel").style.display = "none";
  document.getElementById("login-result").textContent = "Đã đăng xuất";
}

async function loadCustomers() {
  const listEl = document.getElementById("customer-list");
  const resEl = document.getElementById("select-result");
  listEl.innerHTML = "Đang tải...";
  try {
    const res = await fetch("/api/customers/permitted", { credentials: "same-origin" });
    const data = await res.json();
    if (!res.ok) {
      listEl.innerHTML = "";
      resEl.textContent = JSON.stringify(data, null, 2);
      return;
    }
    listEl.innerHTML = "";
    (data.customers || []).forEach((c) => {
      const div = document.createElement("div");
      div.className = "customer-item";
      div.innerHTML =
        "<span><strong>" + c.cif + "</strong> – " + c.customer_name +
        " (" + (c.pricing_tier || c.segment) + ")</span>";
      const btn = document.createElement("button");
      btn.textContent = "Chọn";
      btn.onclick = () => selectCustomer(c.customer_id);
      div.appendChild(btn);
      listEl.appendChild(div);
    });
    resEl.textContent = "Đã tải " + (data.customers || []).length + " CIF";
  } catch (err) {
    listEl.innerHTML = "";
    resEl.textContent = "Lỗi: " + err.message;
  }
}

async function selectCustomer(customerId) {
  const resEl = document.getElementById("select-result");
  const res = await fetch("/api/auth/select-customer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify({ customer_id: customerId }),
  });
  const data = await res.json();
  resEl.textContent = JSON.stringify({ status: res.status, data }, null, 2);
}

let _csrf = sessionStorage.getItem("csrf_token") || "";
async function ensureCsrf() {
  if (_csrf) return _csrf;
  const res = await fetch("/api/auth/me", { credentials: "same-origin" });
  const data = await res.json();
  if (res.ok && data.csrf_token) {
    _csrf = data.csrf_token;
    sessionStorage.setItem("csrf_token", _csrf);
  }
  return _csrf;
}
async function apiPost(path, bodyObj) {
  const body = JSON.stringify(bodyObj);
  const csrf = await ensureCsrf();
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
    credentials: "same-origin", body,
  });
  return { res, data: await res.json() };
}

async function getQuote() {
  const el = document.getElementById("quote-result");
  el.textContent = "Đang lấy giá...";
  const bodyObj = {
    currency: document.getElementById("currency").value,
    side: document.getElementById("side").value,
    amount: Number(document.getElementById("amount").value),
    branch_margin: Number(document.getElementById("branch-margin").value || 0),
  };
  try {
    const { res, data } = await apiPost("/api/transaction/quote", bodyObj);
    el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
    if (res.ok && data.quote && data.quote.quote_id) {
      document.getElementById("quote-id").value = data.quote.quote_id;
    }
  } catch (err) {
    el.textContent = "Lỗi: " + err.message;
  }
}

async function executeTrade() {
  const el = document.getElementById("trade-result");
  el.textContent = "Đang thực hiện...";
  const bodyObj = { quote_id: document.getElementById("quote-id").value };
  try {
    const { res, data } = await apiPost("/api/transaction/execute", bodyObj);
    el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
  } catch (err) {
    el.textContent = "Lỗi: " + err.message;
  }
}

async function loadHistory() {
  const el = document.getElementById("history-result");
  const res = await fetch("/api/transaction/history", { credentials: "same-origin" });
  const data = await res.json();
  el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
}

/* ===== HQ only ===== */
async function loadHQPolicy() {
  const el = document.getElementById("hq-policy-result");
  el.textContent = "Đang tải...";
  const res = await fetch("/api/hq/policy", { credentials: "same-origin" });
  const data = await res.json();
  el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
}

async function updateBaseSpread() {
  const el = document.getElementById("hq-update-result");
  const body = {
    tier: document.getElementById("hq-tier").value,
    currency: document.getElementById("hq-currency").value,
    side: document.getElementById("hq-side").value,
    value: document.getElementById("hq-spread-value").value,
  };
  const res = await fetch("/api/hq/policy/base-spread", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  const data = await res.json();
  el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
}

async function updateMaxMargin() {
  const el = document.getElementById("hq-update-result");
  const body = {
    tier: document.getElementById("hq-tier2").value,
    currency: document.getElementById("hq-currency2").value,
    value: document.getElementById("hq-max-margin").value,
  };
  const res = await fetch("/api/hq/policy/max-branch-margin", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  const data = await res.json();
  el.textContent = JSON.stringify({ status: res.status, data }, null, 2);
}
