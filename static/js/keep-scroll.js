(function () {
  if (location.hash) return;
  var KEY = 'si-scroll:' + location.pathname;
  var saved = null;
  try { saved = parseInt(sessionStorage.getItem(KEY), 10); } catch (e) {}
  if (!(saved > 0)) saved = null;

  try { history.scrollRestoration = 'manual'; } catch (e) {}

  function doScroll() {
    if (saved == null) return;
    var dh = (document.documentElement && document.documentElement.scrollHeight) || 0;
    if (dh < saved) return;
    window.scrollTo(0, saved);
  }

  function save() {
    try { sessionStorage.setItem(KEY, String(window.pageYOffset || 0)); } catch (e) {}
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', doScroll);
  } else {
    doScroll();
  }
  window.addEventListener('load', doScroll);

  var lastH = 0;
  var ro = new ResizeObserver(function () {
    var h = document.documentElement.scrollHeight || 0;
    if (h !== lastH) { lastH = h; doScroll(); }
  });
  ro.observe(document.documentElement);

  var t = null;
  window.addEventListener('scroll', function () {
    var y = window.pageYOffset || 0;
    var h = document.documentElement.scrollHeight || 0;
    if (h < (saved || Infinity) && y < (saved || Infinity)) return;
    saved = y;
    clearTimeout(t);
    t = setTimeout(save, 120);
  }, { passive: true });

  window.addEventListener('pagehide', save);
})();