/* Crypto Hunter dashboard — vanilla JS, no deps */
(function () {
  "use strict";

  var SECTIONS = [
    { key: "listings",  el: "sec-listing",  title: "Listing Terbaru", icon: "\uD83D\uDCC8",
      empty: "Belum ada listing baru. Scanner jalan tiap jam \u2014 cek lagi nanti." },
    { key: "airdrops",  el: "sec-airdrop",  title: "Airdrop",          icon: "\uD83E\uDE82",
      empty: "Belum ada airdrop terpantau. Paket gratis CryptoRank tidak mencakup data drophunting (butuh paket Advanced, $149/bln)." },
    { key: "campaigns", el: "sec-campaign", title: "Campaign",        icon: "\uD83C\uDF81",
      empty: "Belum ada campaign terpantau. Sebagian sumber promo sedang diblokir dari server scan." },
    { key: "unlocks",   el: "sec-unlock",   title: "Token Unlocks",   icon: "\uD83D\uDD13",
      empty: "Belum ada data unlocks. Fetcher unlocks belum tersedia \u2014 datang lagi nanti." }
  ];

  var SRC_NAMES = { binance: "Binance", bybit: "Bybit", okx: "OKX",
    indodax: "Indodax", tokocrypto: "Tokocrypto", pintu: "Pintu",
    cryptorank: "CryptoRank", campaigns: "Campaign" };
  var SRC_LABEL = { ok: "live", error: "offline", need_key: "butuh API key",
    plan_limited: "paket kurang" };

  var EX_COLORS = {
    Binance: "#F0B90B", Bybit: "#F7A600", OKX: "#7dd3fc",
    Indodax: "#60a5fa", Tokocrypto: "#fb923c", Pintu: "#c4b5fd",
    CryptoRank: "#2dd4bf"
  };

  var state = { data: {}, meta: null, filter: "all", failed: [] };

  /* ---------- helpers ---------- */
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }

  function relTime(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return "-";
    var d = Date.now() - t;
    if (d < 0) d = 0;
    var m = Math.floor(d / 60000);
    if (m < 1) return "baru saja";
    if (m < 60) return m + " mnt lalu";
    var h = Math.floor(m / 60);
    if (h < 24) return h + " jam lalu";
    var days = Math.floor(h / 24);
    return days + " hari lalu";
  }

  function fmtCountdown(ms) {
    if (ms <= 0) return "berakhir";
    var s = Math.floor(ms / 1000);
    var d = Math.floor(s / 86400);
    var h = Math.floor((s % 86400) / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (d > 0) return d + "h " + h + "j " + m + "m";
    if (h > 0) return h + "j " + m + "m " + pad(sec) + "d";
    return m + "m " + pad(sec) + "d";
  }

  function el(id) { return document.getElementById(id); }

  /* ---------- render ---------- */
  function badgeColor(ex) { return EX_COLORS[ex] || "#94a3b8"; }

  function renderCard(item, idx) {
    var color = badgeColor(item.exchange);
    var dl = item.deadline ? Date.parse(item.deadline) : NaN;
    var hasDl = !isNaN(dl);
    var urgent = hasDl && (dl - Date.now()) > 0 && (dl - Date.now()) < 24 * 3600 * 1000;
    var ended = hasDl && dl <= Date.now();
    var cls = "card" + (urgent ? " urgent" : "") + (ended ? " ended" : "");

    var h = '<article class="' + cls + '" style="animation-delay:' + Math.min(idx * 45, 450) + 'ms">';
    h += '<div class="row">';
    h += '<span class="badge" style="background:' + color + '">' + esc(item.exchange) + "</span>";
    if (item.is_new) h += '<span class="badge new">BARU</span>';
    h += "</div>";
    h += "<h3>" + (item.url
      ? '<a href="' + esc(item.url) + '" target="_blank" rel="noopener">' + esc(item.judul) + "</a>"
      : esc(item.judul)) + "</h3>";
    h += '<div class="sub">';
    h += "<span>ditemukan " + esc(relTime(item.ditemukan)) + "</span>";
    if (hasDl) h += '<span>\u23F1 <span class="cd" data-deadline="' + item.deadline + '">'
      + esc(fmtCountdown(dl - Date.now())) + "</span></span>";
    if (item.reward) h += '<span class="reward-tag">\uD83C\uDF81 ' + esc(item.reward) + "</span>";
    h += "</div>";
    h += '<div class="actions">';
    if (item.url) h += '<a class="btn-open" href="' + esc(item.url) + '" target="_blank" rel="noopener">Buka \u2197</a>';
    if (item.cara_ikut) h += '<button class="btn-how" type="button">Cara ikut</button>';
    h += "</div>";
    if (item.cara_ikut) h += '<div class="howto">' + esc(item.cara_ikut) + "</div>";
    h += "</article>";
    return h;
  }

  function renderSection(sec) {
    var box = el(sec.el);
    var items = state.data[sec.key] || [];
    var head = box.querySelector(".sec-head .count");
    if (head) head.textContent = items.length + " item";
    var list = box.querySelector(".cards");
    if (!items.length) {
      list.innerHTML = '<div class="empty"><span class="big">' + sec.icon + "</span>"
        + esc(sec.empty) + "</div>";
      return;
    }
    var html = "";
    for (var i = 0; i < items.length; i++) html += renderCard(items[i], i);
    list.innerHTML = html;
  }

  function renderSources() {
    var box = el("sources");
    var meta = state.meta;
    if (!meta || !meta.sources) { box.innerHTML = ""; return; }
    var html = "";
    Object.keys(meta.sources).forEach(function (k) {
      var st = meta.sources[k];
      var cls = st === "ok" ? "ok" : (st === "need_key" || st === "plan_limited" ? "need_key" : "error");
      html += '<span class="src ' + cls + '"><i></i>' + esc(SRC_NAMES[k] || k)
        + " \u00B7 " + esc(SRC_LABEL[st] || st) + "</span>";
    });
    box.innerHTML = html;
  }

  function renderSummary() {
    var total = 0, baru = 0;
    SECTIONS.forEach(function (s) {
      (state.data[s.key] || []).forEach(function (it) {
        total++;
        if (it.is_new) baru++;
      });
    });
    el("summary").innerHTML = "<b>" + total + "</b> item terpantau &nbsp;\u00B7&nbsp; <b>"
      + baru + "</b> baru";
    var ls = state.meta && state.meta.last_scan;
    el("last-scan").textContent = ls
      ? new Date(ls).toLocaleString("id-ID", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })
      : "-";
  }

  function renderAll() {
    SECTIONS.forEach(renderSection);
    renderSources();
    renderSummary();
    applyFilter();
    SECTIONS.forEach(function (s) {
      var chip = document.querySelector('.chip[data-f="' + s.key + '"] small');
      if (chip) chip.textContent = (state.data[s.key] || []).length;
    });
  }

  function applyFilter() {
    SECTIONS.forEach(function (s) {
      var box = el(s.el);
      box.style.display = (state.filter === "all" || state.filter === s.key) ? "" : "none";
    });
    document.querySelectorAll(".chip").forEach(function (c) {
      c.classList.toggle("active", c.getAttribute("data-f") === state.filter);
    });
  }

  /* ---------- load ---------- */
  function fetchJson(path) {
    return fetch(path, { cache: "no-store" }).then(function (r) {
      if (!r.ok) throw new Error(r.status + " " + path);
      return r.json();
    });
  }

  function load(manual) {
    var base = manual ? ("?cb=" + Date.now()) : "";
    SECTIONS.forEach(function (s) {
      el(s.el).querySelector(".cards").innerHTML =
        '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
    });
    var jobs = SECTIONS.map(function (s) {
      return fetchJson("./data/" + s.key + ".json" + base).then(function (d) {
        state.data[s.key] = Array.isArray(d) ? d : [];
      });
    });
    jobs.push(fetchJson("./data/meta.json" + base).then(function (m) {
      state.meta = m;
    }));
    return Promise.all(jobs.map(function (p) {
      return p.catch(function (e) {
        state.failed.push(String(e && e.message || e));
      });
    })).then(function () {
      renderAll();
      var eb = el("errbox");
      if (state.failed.length) {
        eb.style.display = "";
        eb.textContent = "Sebagian data gagal dimuat (" + state.failed.length
          + "). Coba tombol Muat ulang. Detail: " + state.failed.slice(0, 3).join("; ");
      } else {
        eb.style.display = "none";
      }
    });
  }

  /* ---------- ticking countdowns ---------- */
  function tick() {
    var now = Date.now();
    document.querySelectorAll(".cd[data-deadline]").forEach(function (n) {
      var t = Date.parse(n.getAttribute("data-deadline"));
      n.textContent = isNaN(t) ? "-" : fmtCountdown(t - now);
    });
    var ns = el("next-scan");
    var ls = state.meta && state.meta.last_scan ? Date.parse(state.meta.last_scan) : NaN;
    if (isNaN(ls)) { ns.textContent = "-"; return; }
    var remain = ls + 3600 * 1000 - now;
    ns.textContent = remain > 0 ? fmtCountdown(remain) : "segera\u2026";
  }

  /* ---------- wire up ---------- */
  document.querySelectorAll(".chip").forEach(function (c) {
    c.addEventListener("click", function () {
      state.filter = c.getAttribute("data-f");
      applyFilter();
    });
  });

  document.addEventListener("click", function (e) {
    if (e.target && e.target.classList && e.target.classList.contains("btn-how")) {
      var card = e.target.closest(".card");
      var how = card && card.querySelector(".howto");
      if (how) how.classList.toggle("open");
    }
  });

  var btn = el("btn-refresh");
  btn.addEventListener("click", function () {
    btn.disabled = true;
    btn.classList.add("spinning");
    state.failed = [];
    load(true).then(function () {
      btn.disabled = false;
      btn.classList.remove("spinning");
    });
  });

  load(false);
  setInterval(tick, 1000);
  tick();
})();
