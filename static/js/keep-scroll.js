(function () {
  try { history.scrollRestoration = 'manual'; } catch (e) {}
  var KEY = 'si-scroll:' + location.pathname;
  var saved = null;
  try { saved = parseInt(sessionStorage.getItem(KEY), 10); } catch (e) {}
  if (saved > 0) {
    window.addEventListener('load', function () {
      window.scrollTo(0, saved);
    });
  }
  var timer = null;
  window.addEventListener('scroll', function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      try { sessionStorage.setItem(KEY, String(window.pageYOffset || 0)); } catch (e) {}
    }, 150);
  }, { passive: true });
  window.addEventListener('pagehide', function () {
    try { sessionStorage.setItem(KEY, String(window.pageYOffset || 0)); } catch (e) {}
  });
})();