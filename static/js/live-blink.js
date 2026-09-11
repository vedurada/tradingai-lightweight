/* Live Price Blink — flashes .price / .t-price / [data-live] elements whenever
 * their value changes while the Indian market is open (IST Mon–Fri 09:15–15:30).
 * Site-wide, no dependencies. Direction-aware: up = green flash, down = red.
 */
(function () {
  if (window.__liveBlinkLoaded) return;
  window.__liveBlinkLoaded = true;

  var SEL = '.price, .t-price, [data-live]';
  var cache = {};        // path -> {v, dir}
  var maxCache = 2500;
  var raf = null;
  var pending = [];

  function istParts() {
    var p = {};
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Asia/Kolkata',
      weekday: 'short', year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hourCycle: 'h23'
    }).formatToParts(new Date()).forEach(function (x) { p[x.type] = x.value; });
    return p;
  }

  function isMarketOpen() {
    var p = istParts();
    if (!p.weekday || ['Fri', 'Mon', 'Sat', 'Sun', 'Thu', 'Tue', 'Wed'].indexOf(p.weekday) === -1) return false;
    if (p.weekday === 'Sat' || p.weekday === 'Sun') return false;
    var t = parseInt(p.hour, 10) * 60 + parseInt(p.minute, 10);
    return t >= (9 * 60 + 15) && t <= (15 * 60 + 30);
  }

  function pureNum(s) {
    if (!s) return null;
    var t = String(s).trim().replace(/[₹,\s]/g, '');
    if (!/^-?\d+(\.\d+)?$/.test(t)) return null;
    return parseFloat(t);
  }

  function elPath(el) {
    var segs = [], node = el, idx;
    while (node && node !== document.body) {
      idx = Array.prototype.indexOf.call(node.parentElement ? node.parentElement.children : [], node);
      segs.unshift(node.tagName.toLowerCase() + (idx >= 0 ? ':' + idx : ''));
      node = node.parentElement;
    }
    return segs.join('/');
  }

  function flash(el, dir) {
    el.classList.remove('blink-up', 'blink-down');
    void el.offsetWidth; // restart animation
    el.classList.add(dir >= 0 ? 'blink-up' : 'blink-down');
    setTimeout(function () { el.classList.remove('blink-up', 'blink-down'); }, 700);
  }

  function scan(root) {
    var nodes = root.querySelectorAll ? root.querySelectorAll(SEL) : [];
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var v = pureNum(el.textContent);
      if (v === null) continue;
      var p = elPath(el);
      var prev = cache[p];
      if (prev && prev.v !== v) {
        prev.dir = v > prev.v;
        if (isMarketOpen()) pending.push([el, v > prev.v]);
      }
      cache[p] = { v: v, dir: v > (prev ? prev.v : v) };
    }
    if (Object.keys(cache).length > maxCache) cache = {};
  }

  function flush() {
    raf = null;
    for (var i = 0; i < pending.length; i++) flash(pending[i][0], pending[i][1]);
    pending = [];
  }

  new MutationObserver(function (muts) {
    // Evaluate the whole live subtree on any DOM change (cheap for these pages).
    scan(document.documentElement);
    if (pending.length && !raf) raf = requestAnimationFrame(flush);
  }).observe(document.documentElement, { subtree: true, childList: true, characterData: true });

  // Manual trigger for code that swaps a price without a DOM-significant mutation.
  window.blinkPrice = function (el, dir) { if (el) flash(el, dir) };

  // Adaptive polling: 5s during IST market hours, 20s otherwise.
  var FAST = 5000, SLOW = 20000;
  window.marketRefreshMs = function () { return isMarketOpen() ? FAST : SLOW; };
  window.isMarketOpen = isMarketOpen;
})();