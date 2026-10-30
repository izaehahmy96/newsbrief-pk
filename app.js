(function () {
  "use strict";

  // Sections in the order shown. A section with no stories yet is hidden automatically.
  var NAV = [
    { id: "all", label: "Latest" },
    { id: "pakistan", label: "Pakistan" },
    { id: "world", label: "World" },
    { id: "business", label: "Business" },
    { id: "entertainment", label: "Entertainment" },
    { id: "culture", label: "Culture" },
    { id: "lifestyle", label: "Lifestyle" }
  ];
  var ALIAS = { fashion: "lifestyle" };           // older stories used "fashion"
  var JUST_IN_MINUTES = 60;                       // newer than this gets the red JUST IN flag

  var state = { stories: [], category: "all", lang: "all" };
  var feedEl = document.getElementById("feed");
  var tabsEl = document.getElementById("tabs");
  var langsEl = document.getElementById("langs");

  function store(key, val) { try { localStorage.setItem(key, val); } catch (e) {} }
  function recall(key) { try { return localStorage.getItem(key); } catch (e) { return null; } }

  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }

  function catOf(s) { return ALIAS[s.category] || s.category || "pakistan"; }
  function catLabel(id) {
    for (var i = 0; i < NAV.length; i++) if (NAV[i].id === id) return NAV[i].label;
    return id.charAt(0).toUpperCase() + id.slice(1);
  }

  function ageMinutes(iso) {
    var m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    return isNaN(m) ? null : Math.max(0, m);
  }
  function timeAgo(iso) {
    var mins = ageMinutes(iso);
    if (mins == null) return "";
    if (mins < 2) return "Just now";
    if (mins < 60) return mins + " min ago";
    var h = Math.round(mins / 60);
    if (h < 24) return h + " hr ago";
    return Math.round(h / 24) + " d ago";
  }
  function readSeconds(text) {
    var words = (text || "").trim().split(/\s+/).length;
    var secs = Math.round(words / 3.3 / 5) * 5;   // about 200 words a minute
    return Math.max(10, secs);
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || "") ? u : null; }

  function buildCard(s) {
    var isUr = s.lang === "ur";
    var card = el("article", "card");
    card.dir = isUr ? "rtl" : "ltr";
    card.lang = isUr ? "ur" : "en";
    var inner = el("div", "card-inner");

    var pic = el("div", "pic");
    var mark = el("div", "mark");
    var markText = el("span", null, "60");
    markText.appendChild(el("i", null, "."));
    mark.appendChild(markText);
    pic.appendChild(mark);
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
    inner.appendChild(pic);

    var body = el("div", "body");
    var top = el("div", "meta-top");
    top.appendChild(el("span", "cat", catLabel(catOf(s))));
    var age = ageMinutes(s.published);
    if (age != null && age < JUST_IN_MINUTES) top.appendChild(el("span", "flag", "Just in"));
    body.appendChild(top);
    body.appendChild(el("h2", "title", s.title));
    body.appendChild(el("p", "summary", s.summary));
    inner.appendChild(body);

    var foot = el("div", "foot");
    var src = el("span", "src");
    var label = s.source || "";
    var cut = label.indexOf(":");
    if (cut > 0) {
      src.appendChild(document.createTextNode(label.slice(0, cut + 1) + " "));
      src.appendChild(el("b", null, label.slice(cut + 1).trim()));
    } else {
      src.appendChild(el("b", null, label));
    }
    foot.appendChild(src);
    foot.appendChild(el("span", "when", timeAgo(s.published) + " · " + readSeconds(s.summary) + " sec read"));
    inner.appendChild(foot);

    card.appendChild(inner);
    return card;
  }

  function visibleStories() {
    return state.stories.filter(function (s) {
      return (state.category === "all" || catOf(s) === state.category) &&
             (state.lang === "all" || s.lang === state.lang);
    });
  }

  function render() {
    var list = visibleStories();
    feedEl.textContent = "";
    if (!list.length) {
      feedEl.appendChild(el("div", "state", "Nothing here yet. Try another section or language."));
      return;
    }
    var frag = document.createDocumentFragment();
    list.forEach(function (s) { frag.appendChild(buildCard(s)); });
    feedEl.appendChild(frag);
    feedEl.scrollTop = 0;
    // one small swipe hint on the first card; it scrolls away with the card
    var firstPic = feedEl.querySelector(".pic");
    if (firstPic && list.length > 1) firstPic.appendChild(el("span", "hint", "Swipe up ↑"));
  }

  function renderTabs() {
    var have = {};
    state.stories.forEach(function (s) { have[catOf(s)] = true; });
    var shown = NAV.filter(function (n) { return n.id === "all" || have[n.id]; });
    if (!shown.some(function (n) { return n.id === state.category; })) state.category = "all";
    tabsEl.textContent = "";
    shown.forEach(function (n) {
      var btn = el("button", n.id === state.category ? "on" : "", n.label);
      btn.type = "button";
      btn.addEventListener("click", function () {
        state.category = n.id;
        store("nb.cat", n.id);
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

  document.addEventListener("keydown", function (e) {
    var h = feedEl.clientHeight;
    if (e.key === "ArrowDown" || e.key === "PageDown") { feedEl.scrollBy({ top: h, behavior: "smooth" }); e.preventDefault(); }
    if (e.key === "ArrowUp" || e.key === "PageUp") { feedEl.scrollBy({ top: -h, behavior: "smooth" }); e.preventDefault(); }
  });

  function load() {
    fetch("news.json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (data) {
        state.stories = data.stories || [];
        renderTabs();
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
  setInterval(load, 10 * 60 * 1000);   // refresh every 10 minutes while open

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("sw.js").catch(function () {});
    });
  }
})();
