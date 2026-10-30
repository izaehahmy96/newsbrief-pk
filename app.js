(function () {
  "use strict";

  var CATEGORIES = [
    { id: "all", label: "Top" },
    { id: "pakistan", label: "Pakistan" },
    { id: "world", label: "World" },
    { id: "business", label: "Business" },
    { id: "sports", label: "Sports" },
    { id: "entertainment", label: "Entertainment" },
    { id: "fashion", label: "Fashion" }
  ];

  var state = { stories: [], category: "all", lang: "all" };
  var feedEl = document.getElementById("feed");
  var tabsEl = document.getElementById("tabs");
  var langsEl = document.getElementById("langs");
  var hintEl = document.getElementById("hint");

  function store(key, val) { try { localStorage.setItem(key, val); } catch (e) {} }
  function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  function timeAgo(iso) {
    var mins = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
    if (isNaN(mins)) return "";
    if (mins < 60) return mins + " min ago";
    var h = Math.round(mins / 60);
    if (h < 24) return h + " hr ago";
    return Math.round(h / 24) + " d ago";
  }

  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : null; }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function buildCard(s) {
    var isUr = s.lang === "ur";
    var card = el("article", "card");
    card.dir = isUr ? "rtl" : "ltr";
    card.lang = isUr ? "ur" : "en";
    var inner = el("div", "card-inner");

    var pic = el("div", "pic");
    var img = safeUrl(s.image);
    if (img) {
      var im = document.createElement("img");
      im.loading = "lazy";
      im.alt = "";
      im.referrerPolicy = "no-referrer";
      im.onerror = function () { im.remove(); };
      im.src = img;
      pic.appendChild(im);
    }
    pic.appendChild(el("span", "badge", s.category));
    inner.appendChild(pic);

    var body = el("div", "body");
    body.appendChild(el("h2", "title", s.title));
    body.appendChild(el("p", "summary", s.summary));
    inner.appendChild(body);

    var foot = el("div", "foot");
    var meta = el("div", "meta");
    var b = el("b", null, s.source);
    meta.appendChild(b);
    meta.appendChild(document.createTextNode(" · " + timeAgo(s.published)));
    foot.appendChild(meta);
    var link = safeUrl(s.url);
    if (link) {
      var a = el("a", "read", isUr ? "مکمل خبر" : "Read full story");
      a.href = link;
      a.target = "_blank";
      a.rel = "noopener noreferrer";
      foot.appendChild(a);
    }
    inner.appendChild(foot);
    card.appendChild(inner);
    return card;
  }

  function render() {
    var list = state.stories.filter(function (s) {
      return (state.category === "all" || s.category === state.category) &&
             (state.lang === "all" || s.lang === state.lang);
    });
    feedEl.textContent = "";
    if (!list.length) {
      feedEl.appendChild(el("div", "state", "No stories here yet. Try another category or language."));
      return;
    }
    var frag = document.createDocumentFragment();
    list.forEach(function (s) { frag.appendChild(buildCard(s)); });
    feedEl.appendChild(frag);
    feedEl.scrollTop = 0;
  }

  function renderTabs() {
    tabsEl.textContent = "";
    CATEGORIES.forEach(function (c) {
      var btn = el("button", c.id === state.category ? "on" : "", c.label);
      btn.type = "button";
      btn.addEventListener("click", function () {
        state.category = c.id;
        store("nb.cat", c.id);
        renderTabs();
        render();
      });
      tabsEl.appendChild(btn);
    });
  }

  function renderLangs() {
    Array.prototype.forEach.call(langsEl.querySelectorAll("button"), function (b) {
      b.classList.toggle("on", b.getAttribute("data-lang") === state.lang);
    });
  }

  langsEl.addEventListener("click", function (e) {
    var b = e.target.closest("button");
    if (!b) return;
    state.lang = b.getAttribute("data-lang");
    store("nb.lang", state.lang);
    renderLangs();
    render();
  });

  // keyboard: arrow keys / space move one card
  document.addEventListener("keydown", function (e) {
    var h = feedEl.clientHeight;
    if (e.key === "ArrowDown" || e.key === "PageDown") { feedEl.scrollBy({ top: h, behavior: "smooth" }); e.preventDefault(); }
    if (e.key === "ArrowUp" || e.key === "PageUp") { feedEl.scrollBy({ top: -h, behavior: "smooth" }); e.preventDefault(); }
  });

  feedEl.addEventListener("scroll", function () { hintEl.classList.add("gone"); }, { passive: true });

  function load() {
    fetch("news.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        state.stories = data.stories || [];
        render();
      })
      .catch(function () {
        feedEl.textContent = "";
        feedEl.appendChild(el("div", "state", "Couldn't load the news. Check your connection and refresh."));
      });
  }

  state.category = recall("nb.cat") || "all";
  state.lang = recall("nb.lang") || "all";
  renderTabs();
  renderLangs();
  load();
  setInterval(load, 10 * 60 * 1000); // refresh every 10 minutes while open

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    });
  }
})();
