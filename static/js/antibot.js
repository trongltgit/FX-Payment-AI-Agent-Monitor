/**
 * Anti-Bot client helper – nạp TRƯỚC mọi script khác.
 *  1) Tự gắn X-CSRF-Token cho mọi request ghi (POST/PUT/PATCH/DELETE) tới /api/
 *  2) Tự giải Proof-of-Work khi server trả 428 CHALLENGE_REQUIRED rồi gửi lại 1 lần
 *  3) Bộ giải PoW SHA-256 thuần JS (không phụ thuộc thư viện)
 */
(function () {
  "use strict";

  // ---------- SHA-256 1 khối (thông điệp < 56 byte: prefix 24 ký tự + nonce <= 20 chữ số) ----------
  const K = new Uint32Array([
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2]);
  const H0 = [0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19];

  function makeHasher(prefix) {
    const pre = new TextEncoder().encode(prefix);
    const block = new Uint8Array(64);
    const w = new Uint32Array(64);
    block.set(pre, 0);
    // trả về [word0, word1] của digest (đủ để đếm tối đa 64 bit 0 đầu)
    return function (nonce) {
      const s = String(nonce);
      let n = pre.length;
      for (let i = 0; i < s.length; i++) block[n++] = s.charCodeAt(i);
      block[n] = 0x80;
      for (let i = n + 1; i < 64; i++) block[i] = 0;
      const bitLen = n * 8;
      block[62] = (bitLen >>> 8) & 0xff; block[63] = bitLen & 0xff;
      for (let i = 0; i < 16; i++)
        w[i] = (block[4*i] << 24) | (block[4*i+1] << 16) | (block[4*i+2] << 8) | block[4*i+3];
      for (let i = 16; i < 64; i++) {
        const a = w[i-15], b = w[i-2];
        const s0 = ((a >>> 7) | (a << 25)) ^ ((a >>> 18) | (a << 14)) ^ (a >>> 3);
        const s1 = ((b >>> 17) | (b << 15)) ^ ((b >>> 19) | (b << 13)) ^ (b >>> 10);
        w[i] = (w[i-16] + s0 + w[i-7] + s1) | 0;
      }
      let a=H0[0],b=H0[1],c=H0[2],d=H0[3],e=H0[4],f=H0[5],g=H0[6],h=H0[7];
      for (let i = 0; i < 64; i++) {
        const S1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7));
        const ch = (e & f) ^ (~e & g);
        const t1 = (h + S1 + ch + K[i] + w[i]) | 0;
        const S0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10));
        const mj = (a & b) ^ (a & c) ^ (b & c);
        const t2 = (S0 + mj) | 0;
        h = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      return [(H0[0] + a) >>> 0, (H0[1] + b) >>> 0];
    };
  }

  function leadingZeroBits(w0, w1) {
    if (w0 !== 0) return Math.clz32(w0);
    if (w1 !== 0) return 32 + Math.clz32(w1);
    return 64;
  }

  /** Tìm nonce sao cho SHA-256(prefix+nonce) có >= bits bit 0 đứng đầu. Chia nhỏ để không treo giao diện. */
  async function solvePow(prefix, bits) {
    const hash = makeHasher(prefix);
    let nonce = 0;
    for (;;) {
      const end = nonce + 20000;
      for (; nonce < end; nonce++) {
        const r = hash(nonce);
        if (leadingZeroBits(r[0], r[1]) >= bits) return nonce;
      }
      await new Promise((res) => setTimeout(res, 0));
    }
  }

  // ---------- CSRF + tự động giải challenge ----------
  const nativeFetch = window.fetch.bind(window);
  const UNSAFE = ["POST", "PUT", "PATCH", "DELETE"];

  async function getCsrf() {
    let t = sessionStorage.getItem("csrf_token");
    if (!t) {
      try {
        const r = await nativeFetch("/api/auth/me", { credentials: "same-origin" });
        const d = await r.json();
        if (r.ok && d.csrf_token) { t = d.csrf_token; sessionStorage.setItem("csrf_token", t); }
      } catch (e) { /* bỏ qua */ }
    }
    return t || "";
  }

  window.fetch = async function (input, init) {
    init = Object.assign({}, init || {});
    const method = (init.method || "GET").toUpperCase();
    const url = typeof input === "string" ? input : (input && input.url) || "";
    const sameOrigin = url.startsWith("/") || url.startsWith(location.origin);
    const isApi = sameOrigin && url.indexOf("/api/") !== -1;

    if (isApi && UNSAFE.includes(method) && url.indexOf("/api/auth/login") === -1) {
      const headers = new Headers(init.headers || {});
      if (!headers.has("X-CSRF-Token")) headers.set("X-CSRF-Token", await getCsrf());
      init.headers = headers;
    }
    const retried = init._abRetried; delete init._abRetried;
    const res = await nativeFetch(input, init);

    if (isApi && res.status === 428 && !retried) {
      let data = null;
      try { data = await res.clone().json(); } catch (e) { /* không phải JSON */ }
      if (data && data.error === "CHALLENGE_REQUIRED" && data.challenge) {
        const nonce = await solvePow(data.challenge.prefix, data.challenge.bits);
        const headers = new Headers(init.headers || {});
        headers.set("X-Challenge-Id", data.challenge.challenge_id);
        headers.set("X-Challenge-Nonce", String(nonce));
        return window.fetch(input, Object.assign({}, init, { headers, _abRetried: true }));
      }
    }
    if (isApi && url.indexOf("/api/auth/logout") !== -1 && res.ok) sessionStorage.removeItem("csrf_token");
    return res;
  };

  window.AB = { solvePow: solvePow, getCsrf: getCsrf, _makeHasher: makeHasher, _lzb: leadingZeroBits };
})();
