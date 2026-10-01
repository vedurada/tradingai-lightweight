/* TradingAI.in share buttons – no SDKs, privacy-friendly.
   Auto-injects a "Share this page" bar above <footer> + a floating mobile share button.
   Uses official share URLs: X, Facebook, WhatsApp, LinkedIn, Telegram, Copy + native share.
   Instagram has no web share URL, so its button copies the link then opens Instagram. */
(function () {
  if (document.getElementById("tai-share-bar")) return;

  function pageUrl() {
    var canonical = document.querySelector('link[rel="canonical"]');
    var href = canonical && canonical.href ? canonical.href : window.location.href;
    return href.split("#")[0];
  }
  function pageTitle() {
    return document.title || "TradingAI.in";
  }
  function pageText() {
    var m = document.querySelector('meta[name="description"]');
    var desc = m && m.content ? m.content : "";
    var t = pageTitle();
    var s = t + (desc ? " — " + desc : "");
    if (s.length > 220) s = s.slice(0, 217) + "...";
    return s + " via TradingAI.in (educational market analytics, not investment advice)";
  }

  var url = pageUrl();
  var text = pageText();
  var eu = encodeURIComponent(url);
  var et = encodeURIComponent(text);

  var targets = [
    { key: "x", label: "Share on X", href: "https://twitter.com/intent/tweet?text=" + et + "&url=" + eu,
      svg: '<path d="M17.5 3h3.1l-6.8 7.8L21.8 21h-6.3l-4.9-6.4L5 21H1.9l7.3-8.3L2.2 3h6.4l4.4 5.9L17.5 3zm-1.1 16.1h1.7L7.7 4.8H5.9l10.5 14.3z"/>' },
    { key: "facebook", label: "Share on Facebook", href: "https://www.facebook.com/sharer/sharer.php?u=" + eu,
      svg: '<path d="M13.5 21v-7h2.4l.4-3h-2.8V9.1c0-.9.3-1.5 1.6-1.5h1.3V4.9c-.3 0-1.1-.1-2.1-.1-2.1 0-3.6 1.3-3.6 3.7V11H8.3v3h2.4v7h2.8z"/>' },
    { key: "whatsapp", label: "Share on WhatsApp", href: "https://wa.me/?text=" + encodeURIComponent(text + " " + url),
      svg: '<path d="M12 3a9 9 0 0 0-7.8 13.5L3 21l4.6-1.2A9 9 0 1 0 12 3zm0 1.8a7.2 7.2 0 1 1-3.7 13.4l-.3-.2-2.7.7.7-2.6-.2-.3A7.2 7.2 0 0 1 12 4.8zm-3 3.3c-.2 0-.5 0-.7.3-.2.3-.9.9-.9 2.1s.9 2.5 1 2.6c.1.1 1.9 3 4.6 4.1 2.3.9 2.8.7 3.3.7.5-.1 1.6-.7 1.9-1.3.2-.6.2-1.1.2-1.3-.1-.1-.3-.2-.6-.3l-2-1c-.3-.1-.5-.2-.7 0l-.9 1.1c-.2.2-.3.2-.6.1a7.6 7.6 0 0 1-2.2-1.4 8.2 8.2 0 0 1-1.5-1.9c-.2-.3 0-.4.1-.6l.5-.6c.1-.2.2-.3.3-.5.1-.2 0-.4 0-.5L9.3 8c-.2-.4-.4-.4-.6-.4H9z"/>' },
    { key: "linkedin", label: "Share on LinkedIn", href: "https://www.linkedin.com/sharing/share-offsite/?url=" + eu,
      svg: '<path d="M6.9 8.6H4V20h2.9V8.6zM5.4 3.5a1.7 1.7 0 1 0 0 3.4 1.7 1.7 0 0 0 0-3.4zM10 20v-6c0-1.5.8-2.6 2.3-2.6 1.4 0 2 1 2 2.6v6h2.9v-6.4c0-3-1.6-4.4-3.8-4.4-1.7 0-2.6 1-3 1.7V8.6H7.5V20H10z"/>' },
    { key: "telegram", label: "Share on Telegram", href: "https://t.me/share/url?url=" + eu + "&text=" + et,
      svg: '<path d="M21 4 3.5 11.1c-.7.3-.7 1.2.1 1.4l4.4 1.4 1.7 5.3c.3.8 1.3.9 1.8.2l2.5-2.9 4.7 3.5c.6.4 1.5.1 1.7-.6L21.9 5c.2-.9-.5-1.3-.9-1zM8.6 13.1l9.5-7.5c.1-.1.3 0 .2.2l-7.8 7.4-.3 3-1.6-3.1z"/>' }
  ];

  var bar = document.createElement("div");
  bar.id = "tai-share-bar";
  bar.setAttribute("role", "group");
  bar.setAttribute("aria-label", "Share this page");

  var buttonsHtml = targets.map(function (t) {
    return '<a class="tai-share-btn tai-share-' + t.key + '" href="' + t.href + '" target="_blank" rel="noopener nofollow" aria-label="' + t.label + '" title="' + t.label + '">' +
      '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' + t.svg + "</svg>" +
      "<span>" + t.key.charAt(0).toUpperCase() + t.key.slice(1) + "</span></a>";
  }).join("");

  bar.innerHTML =
    '<span class="tai-share-label">Found this useful? Share it:</span>' +
    '<span class="tai-share-btns">' + buttonsHtml +
    '<button type="button" class="tai-share-btn tai-share-instagram" data-action="instagram" aria-label="Share on Instagram" title="Share on Instagram">' +
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 4c-2.7 0-3 0-4.1.1-1.1 0-1.8.2-2.4.5-.6.2-1.1.6-1.6 1.1-.5.5-.9 1-1.1 1.6-.3.6-.5 1.3-.5 2.4.1 1.1.1 1.4.1 2.3s0 1.2-.1 2.3c0 1.1-.2 1.8-.5 2.4-.2.6-.6 1.1-1.1 1.6-.5.5-1 .9-1.6 1.1-.6.3-1.3.5-2.4.5C9 20 9.3 20 12 20s3 0 4.1-.1c1.1 0 1.8-.2 2.4-.5.6-.2 1.1-.6 1.6-1.1.5-.5.9-1 1.1-1.6.3-.6.5-1.3.5-2.4.1-1.1.1-1.4.1-2.3s0-1.2-.1-2.3c0-1.1-.2-1.8-.5-2.4-.2-.6-.6-1.1-1.1-1.6-.5-.5-1-.9-1.6-1.1-.6-.3-1.3-.5-2.4-.5C15 4 14.7 4 12 4zm0 1.8c2.6 0 3 0 4 .1 1 0 1.5.2 1.9.3.5.2.8.4 1.1.7.3.3.5.6.7 1.1.1.4.3.9.3 1.9.1 1 .1 1.4.1 2.1s0 1-.1 2.1c0 1-.2 1.5-.3 1.9-.2.5-.4.8-.7 1.1-.3.3-.6.5-1.1.7-.4.1-.9.3-1.9.3-1 .1-1.4.1-4 .1s-3 0-4-.1c-1 0-1.5-.2-1.9-.3-.5-.2-.8-.4-1.1-.7-.3-.3-.5-.6-.7-1.1-.1-.4-.3-.9-.3-1.9C4 13.1 4 12.7 4 12s0-1.1.1-2.1c0-1 .2-1.5.3-1.9.2-.5.4-.8.7-1.1.3-.3.6-.5 1.1-.7.4-.1.9-.3 1.9-.3 1-.1 1.4-.1 4-.1zm0 3.1a5.1 5.1 0 1 0 0 10.2 5.1 5.1 0 0 0 0-10.2zm0 8.4a3.3 3.3 0 1 1 0-6.6 3.3 3.3 0 0 1 0 6.6zm5.3-8.6a1.2 1.2 0 1 1-2.4 0 1.2 1.2 0 0 1 2.4 0z"/></svg><span>Instagram</span></button>' +
    '<button type="button" class="tai-share-btn tai-share-copy" data-action="copy" aria-label="Copy page link" title="Copy page link">' +
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M9 9h9v11H9zM6 4h9v2H8v7H6z" fill-rule="evenodd"/><path d="M9 9h9v11H9V9zm1.5 1.5v8h6v-8h-6zM6 4h9v2H8v7H6V4z"/></svg><span>Copy</span></button>' +
    '<button type="button" class="tai-share-btn tai-share-more" data-action="native" aria-label="More share options" title="More share options">' +
    '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 5.5A1.8 1.8 0 1 0 12 9a1.8 1.8 0 0 0 0-3.5zm0 5.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6zm0 5.3a1.8 1.8 0 1 0 0 3.5 1.8 1.8 0 0 0 0-3.5zM18.5 7.5l-5 2.6.7 1.4 5-2.6-.7-1.4zM18.5 16.5l-5-2.6.7-1.4 5 2.6-.7 1.4zM5.5 7.5l5 2.6-.7 1.4-5-2.6.7-1.4zm0 9l5-2.6-.7-1.4-5 2.6.7 1.4z"/></svg><span>More</span></button>' +
    "</span>" +
    '<span class="tai-share-note" role="status" aria-live="polite"></span>';

  function mount() {
    var footer = document.querySelector("footer");
    if (footer && footer.parentNode) {
      footer.parentNode.insertBefore(bar, footer);
    } else {
      document.body.appendChild(bar);
    }
  }
  mount();

  function note(msg) {
    var n = bar.querySelector(".tai-share-note");
    if (!n) return;
    n.textContent = msg;
    clearTimeout(note._t);
    note._t = setTimeout(function () { n.textContent = ""; }, 2500);
  }

  bar.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-action]");
    if (!btn) return;
    var action = btn.getAttribute("data-action");
    if (action === "copy") {
      ev.preventDefault();
      var done = function () { note("Link copied — paste it anywhere to share."); };
      var fail = function () { note("Copy failed — long-press the URL to copy."); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(done, function () { fallbackCopy(fail); });
      } else {
        fallbackCopy(done, fail);
      }
    } else if (action === "instagram") {
      ev.preventDefault();
      try { if (window.gtag) window.gtag("event", "share", { event_label: "Share on Instagram", page: url }); } catch (e) {}
      var openIg = function () { try { window.open("https://www.instagram.com/", "_blank", "noopener"); } catch (e) {} };
      var doneIg = function () { note("Link copied — paste it in Instagram Stories, Reels or DMs."); openIg(); };
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(doneIg, function () { fallbackCopy(doneIg); });
      } else {
        fallbackCopy(doneIg);
      }
    } else if (action === "native") {
      ev.preventDefault();
      if (navigator.share) {
        navigator.share({ title: pageTitle(), text: text, url: url }).catch(function () {});
      } else {
        note("Use the buttons above, or Copy to share anywhere.");
      }
    }
  });

  function fallbackCopy(ok, fail) {
    try {
      var ta = document.createElement("textarea");
      ta.value = url;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      var res = document.execCommand("copy");
      document.body.removeChild(ta);
      if (res) { (ok || function () {})(); } else { (fail || ok)(); }
    } catch (e) { (fail || function () {})(); }
  }

  // UTM-friendly: tag outbound clicks for analytics without breaking share URLs
  bar.querySelectorAll("a.tai-share-btn").forEach(function (a) {
    a.addEventListener("click", function () {
      try {
        if (window.gtag) window.gtag("event", "share", { event_label: a.getAttribute("aria-label"), page: url });
      } catch (e) {}
    });
  });
})();
