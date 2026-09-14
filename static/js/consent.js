/* TradingAI.in cookie consent (Track B). First-party only: no cookies set by
 * this banner itself. Choice persisted in localStorage as tai_consent.
 * Reject => non-personalised ads + consent-mode defaults denied. */
(function () {
  'use strict';
  var KEY = 'tai_consent';

  function read() {
    try {
      var raw = window.localStorage.getItem(KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }
  function write(state) {
    try {
      window.localStorage.setItem(KEY, JSON.stringify(
        { state: state, ts: new Date().toISOString() }));
    } catch (e) { /* storage unavailable: banner simply reappears */ }
  }
  function applyDenied() {
    try {
      (window.adsbygoogle = window.adsbygoogle || []).requestNonPersonalizedAds = 1;
    } catch (e) { /* ads not loaded yet: flag still set on the queue object */ }
    try {
      if (typeof window.gtag === 'function') {
        window.gtag('consent', 'default',
          { ad_storage: 'denied', analytics_storage: 'denied' });
      }
    } catch (e) { /* gtag absent: nothing to configure */ }
  }
  function choose(state) {
    write(state);
    if (state === 'denied') { applyDenied(); }
    hide();
  }
  function hide() {
    var el = document.getElementById('tai-consent');
    if (el && el.parentNode) { el.parentNode.removeChild(el); }
  }
  function show() {
    if (document.getElementById('tai-consent')) { return; }
    var bar = document.createElement('div');
    bar.id = 'tai-consent';
    bar.setAttribute('role', 'dialog');
    bar.setAttribute('aria-live', 'polite');
    bar.setAttribute('aria-label', 'Cookie consent');
    bar.style.cssText = 'position:fixed;left:0;right:0;bottom:0;z-index:9999;' +
      'background:#0f172a;color:#e2e8f0;padding:12px 16px;font-size:14px;' +
      'display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:center;' +
      'box-shadow:0 -2px 12px rgba(0,0,0,.35);';
    var msg = document.createElement('span');
    msg.style.cssText = 'max-width:640px;';
    msg.innerHTML = 'We use cookies for analytics and advertising (Google AdSense). ' +
      'Choose Accept for personalised ads, or Reject for non-personalised ads. ' +
      'See our <a href="/privacy.html" style="color:#93c5fd">Privacy Policy</a>.';
    function btn(label, state) {
      var b = document.createElement('button');
      b.type = 'button';
      b.textContent = label;
      b.style.cssText = 'background:#2563eb;color:#fff;border:0;border-radius:6px;' +
        'padding:8px 16px;cursor:pointer;font-size:14px;';
      b.addEventListener('click', function () { choose(state); });
      return b;
    }
    bar.appendChild(msg);
    bar.appendChild(btn('Accept', 'granted'));
    bar.appendChild(btn('Reject', 'denied'));
    document.body.appendChild(bar);
  }

  var saved = read();
  if (!saved) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', show);
    } else { show(); }
  } else if (saved.state === 'denied') {
    applyDenied();
  }

  window.TAIConsent = { show: show, hide: hide, read: read };
})();
