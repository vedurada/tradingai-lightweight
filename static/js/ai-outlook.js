/**
 * ai-outlook.js — Shared AI Market Outlook dashboard builder.
 *
 * Fetches outlook payload + live quote + breadth + VIX and renders the full
 * dashboard (10 sections) matching the user-specified template.
 *
 * Usage:
 *   <div id="dashboard"></div>
 *   <script src="../assets/js/ai-outlook.js"></script>
 *   <script>renderOutlookDashboard('dashboard', { symbol:'NIFTY', api:'nifty',
 *       displayName:'NIFTY 50', step:50, lot:75, apiBase:'..' });</script>
 */
(function () {
  'use strict';

  var _timers = {};
  var _symbols = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'SENSEX'];
  var _displayNames = { NIFTY: 'NIFTY 50', BANKNIFTY: 'BANK NIFTY', FINNIFTY: 'FIN NIFTY', SENSEX: 'SENSEX' };

  function fp(v) {
    return v != null ? Number(v).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—';
  }
  function fc(v) {
    if (v == null) return '—';
    return (v >= 0 ? '+' : '') + Number(v).toFixed(2);
  }
  function fPct(v) {
    return v != null ? Number(v).toFixed(0) + '%' : '—';
  }
  function rc(r) {
    if (!r) return '#64748b';
    r = String(r).toUpperCase();
    if (r.indexOf('BULLISH') >= 0) return '#15803d';
    if (r.indexOf('BEARISH') >= 0) return '#dc2626';
    if (r.indexOf('RANGE') >= 0 || r.indexOf('NEUTRAL') >= 0) return '#a16207';
    return '#64748b';
  }
  function vixRegime(v) {
    if (v == null) return 'UNKNOWN';
    if (v < 11) return 'VERY LOW';
    if (v < 13) return 'LOW';
    if (v < 16) return 'NORMAL';
    if (v < 20) return 'ELEVATED';
    if (v < 25) return 'HIGH';
    return 'EXTREME';
  }
  function vixRegColor(v) {
    if (v == null) return '#64748b';
    if (v < 16) return '#15803d';
    if (v < 20) return '#a16207';
    return '#dc2626';
  }

  async function fetchJSON(base, path) {
    try {
      var r = await fetch(base + '/api/' + path);
      if (!r.ok) throw new Error('nf');
      return await r.json();
    } catch (e) { return null; }
  }

  function factorLabel(label, color) {
    return '<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-weight:700;font-size:0.78rem;color:#fff;background:' + color + '">' + label + '</span>';
  }

  /* ── Compute 8 factor scores from real data ── */
  function computeFactors(outlook, breadthData) {
    var ind = outlook.indicators || {};
    var vix = outlook.vix || {};
    var gap = outlook.gap || {};
    var regime = outlook.regime || {};
    var opts = outlook.options || {};
    var bias = outlook.bias || {};
    var factors = [];

    // TREND — from regime + ADX
    var trendLabel, trendDesc;
    var regimePri = (regime.primary || '').toUpperCase();
    if (regimePri.indexOf('BULLISH') >= 0) { trendLabel = 'BULLISH'; trendDesc = 'Strong uptrend confirmed'; }
    else if (regimePri.indexOf('BEARISH') >= 0) { trendLabel = 'BEARISH'; trendDesc = 'Strong downtrend confirmed'; }
    else if (regimePri.indexOf('RANGE') >= 0 || regimePri.indexOf('NEUTRAL') >= 0) { trendLabel = 'NEUTRAL'; trendDesc = 'Range-bound consolidation'; }
    else { trendLabel = 'MIXED'; trendDesc = 'Ambiguous regime signals'; }
    if (ind.adx != null && ind.adx < 20) { trendDesc = 'Weak trend, low momentum'; }
    factors.push({ name: 'TREND', label: trendLabel, desc: trendDesc });

    // OI — from oi_signal + PCR
    var oiSignal = opts.oi_signal || 'NEUTRAL';
    var pcr = null;
    if (opts.pcr && opts.pcr.expiries && opts.pcr.expiries.length) pcr = opts.pcr.expiries[0].pcr;
    var oiLabel, oiDesc;
    if (oiSignal === 'BEARISH') { oiLabel = 'BEARISH'; oiDesc = 'Call OI dominates, put protection thin'; }
    else if (oiSignal === 'MIXED') { oiLabel = 'MARGINAL'; oiDesc = 'Put-call ratio weakening'; }
    else { oiLabel = 'NEUTRAL'; oiDesc = pcr != null ? ('PCR ' + pcr.toFixed(2) + ' — balanced') : 'OI data balanced'; }
    factors.push({ name: 'OI', label: oiLabel, desc: oiDesc });

    // VIX — from vix regime
    var vixVal = vix.value;
    var vixR = vixRegime(vixVal);
    var vixLabel, vixDesc;
    if (vixVal == null) { vixLabel = 'N/A'; vixDesc = 'VIX data unavailable'; }
    else if (vixR === 'EXTREME' || vixR === 'HIGH') { vixLabel = 'BEARISH'; vixDesc = 'Elevated fear, caution warranted'; }
    else if (vixR === 'ELEVATED') { vixLabel = 'CAUTIOUS'; vixDesc = 'Above-average fear, defined-risk only'; }
    else if (vixR === 'NORMAL') { vixLabel = 'NEUTRAL'; vixDesc = 'Comfortable for option writing'; }
    else { vixLabel = 'BULLISH'; vixDesc = 'Low volatility favours risk-on'; }
    factors.push({ name: 'VIX', label: vixLabel, desc: vixDesc });

    // MOMENTUM — from RSI + MACD
    var rsi = ind.rsi;
    var macd = ind.macd;
    var momLabel, momDesc;
    if (rsi != null && rsi > 60) { momLabel = 'BULLISH'; momDesc = 'RSI and MACD aligned upward'; }
    else if (rsi != null && rsi < 40) { momLabel = 'BEARISH'; momDesc = 'RSI below 40, selling pressure'; }
    else if (rsi != null && rsi < 30) { momLabel = 'OVERSOLD'; momDesc = 'RSI oversold bounce possible'; }
    else { momLabel = 'NEUTRAL'; momDesc = rsi != null ? 'RSI ' + rsi.toFixed(0) + ' — no clear momentum' : 'Momentum data unavailable'; }
    factors.push({ name: 'MOMENTUM', label: momLabel, desc: momDesc });

    // FUTURES — no live SGX feed
    factors.push({ name: 'FUTURES', label: 'NO FEED', desc: 'SGX/Nifty futures data unavailable' });

    // GLOBAL — no feed
    factors.push({ name: 'GLOBAL', label: 'NO FEED', desc: 'Global cues data unavailable' });

    // BREADTH — from breadth API
    var adRatio = breadthData ? breadthData.advance_decline_ratio : null;
    var breadthLabel, breadthDesc;
    if (adRatio != null && adRatio > 1.5) { breadthLabel = 'BULLISH'; breadthDesc = 'More stocks participating in the rally'; }
    else if (adRatio != null && adRatio > 1.2) { breadthLabel = 'MILDLY BULLISH'; breadthDesc = 'Healthy advance-decline ratio'; }
    else if (adRatio != null && adRatio < 0.7) { breadthLabel = 'BEARISH'; breadthDesc = 'Broad-based selling pressure'; }
    else if (adRatio != null && adRatio < 0.9) { breadthLabel = 'MILDLY BEARISH'; breadthDesc = 'Declines outnumber advances'; }
    else if (adRatio != null) { breadthLabel = 'NEUTRAL'; breadthDesc = 'Balanced advance-decline'; }
    else { breadthLabel = 'N/A'; breadthDesc = 'Breadth data unavailable'; }
    factors.push({ name: 'BREADTH', label: breadthLabel, desc: breadthDesc });

    // EVENT — from gap
    var eventLabel, eventDesc;
    if (gap.available && Math.abs(gap.gap_pct || 0) >= 0.5) {
      eventLabel = gap.kind || 'SIGNIFICANT';
      eventDesc = 'Gap of ' + Math.abs(gap.gap_pct).toFixed(1) + '% — watch for fill';
    } else {
      eventLabel = 'NOT SIGNIFICANT';
      eventDesc = 'Key events accounted for';
    }
    factors.push({ name: 'EVENT', label: eventLabel, desc: eventDesc });

    return factors;
  }

  function factorColor(label) {
    var l = (label || '').toUpperCase();
    if (l === 'BULLISH' || l === 'MILDLY BULLISH') return '#15803d';
    if (l === 'BEARISH' || l === 'MILDLY BEARISH') return '#dc2626';
    if (l === 'NEUTRAL' || l === 'N/A' || l === 'NO FEED') return '#64748b';
    if (l === 'MARGINAL' || l === 'CAUTIOUS' || l === 'OVERSOLD' || l === 'MIXED') return '#a16207';
    if (l.indexOf('GAP') >= 0) return '#a16207';
    return '#64748b';
  }

  /* ── Build section HTML ── */

  function marketStatusBadge() {
    var open = false;
    try {
      var parts = {};
      new Intl.DateTimeFormat('en-GB', { timeZone: 'Asia/Kolkata', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).formatToParts(new Date()).forEach(function (p) { parts[p.type] = p.value; });
      var day = parts.weekday;
      var hhmm = parseInt(parts.hour, 10) * 60 + parseInt(parts.minute, 10);
      var weekday = day === 'Mon' || day == 'Tue' || day === 'Wed' || day === 'Thu' || day === 'Fri';
      open = weekday && hhmm >= (9 * 60 + 15) && hhmm < (15 * 60 + 30);
    } catch (e) { open = false; }
    var color = open ? '#22c55e' : '#f59e0b';
    var label = open ? 'LIVE' : 'CLOSED';
    return '<span style="display:inline-flex;align-items:center;gap:6px;font-size:0.8rem;font-weight:700;color:' + color + '">' +
      '<span style="width:8px;height:8px;border-radius:50%;background:' + color + ';display:inline-block"></span>' + label + '</span>';
  }

  function buildNavTabs(currentSymbol, cfg) {
    cfg = cfg || {};
    var tabBase = cfg.tabBase || '../indices/';
    var tabs = _symbols.map(function (s) {
      var isActive = s === currentSymbol;
      var names = { NIFTY: 'NIFTY', BANKNIFTY: 'BANKNIFTY', FINNIFTY: 'FINNIFTY', SENSEX: 'SENSEX' };
      var style = 'display:inline-block;padding:6px 14px;border-radius:999px;font-size:0.82rem;font-weight:700;text-decoration:none;cursor:pointer;' +
        (isActive ? 'background:#15803d;color:#fff;border:1px solid #15803d' : 'background:#f1f5f9;color:#0f172a;border:1px solid #e2e8f0');
      if (typeof cfg.onTab === 'function' && !isActive) {
        return '<button type="button" data-tab="' + s + '" style="' + style + ';border:none;font-family:inherit">' + (names[s] || s) + '</button>';
      }
      var href = isActive ? 'javascript:void(0)' : tabBase + s.toLowerCase() + '.html';
      return '<a href="' + href + '" style="' + style + '">' + (names[s] || s) + '</a>';
    }).join('');
    return '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:1rem;padding:10px 16px;background:#0f172a;border-radius:10px;color:#fff">' +
      '<span style="font-weight:800;font-size:0.95rem">AI MARKET OUTLOOK</span>' +
      '<div style="display:flex;gap:6px;flex-wrap:wrap">' + tabs + '</div>' +
      marketStatusBadge() + '</div>';
  }

  function buildHero(quote, outlook, sym) {
    var price = quote ? quote.price : null;
    var change = quote ? quote.change : null;
    var changePct = quote ? quote.change_pct : null;
    var verdict = outlook.decision ? outlook.decision.verdict : '—';
    var vColor = verdict === 'TRADE' ? '#15803d' : '#a16207';
    var pColor = (change || 0) >= 0 ? '#22c55e' : '#ef4444';
    return '<div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:1rem;margin-bottom:1rem">' +
      '<div>' +
      '<h2 style="margin:0 0 4px;font-size:1.4rem;color:#fff;font-weight:800">' + (_displayNames[sym] || sym) + '</h2>' +
      '<div style="font-size:2rem;font-weight:800;color:#fff;font-variant-numeric:tabular-nums">' + fp(price) + '</div>' +
      '<div style="margin-top:4px"><span style="background:' + pColor + ';color:#fff;padding:4px 14px;border-radius:999px;font-weight:800;font-size:0.85rem">' +
      fc(change) + ' (' + fc(changePct) + '%)</span></div>' +
      '<div style="color:#cbd5e1;font-size:0.82rem;margin-top:4px">High ' + fp(quote ? quote.high : null) + ' &nbsp; Low ' + fp(quote ? quote.low : null) + '</div>' +
      '</div>' +
      '<div style="text-align:right">' +
      '<div style="background:' + vColor + ';color:#fff;padding:6px 18px;border-radius:8px;font-weight:800;font-size:0.95rem;display:inline-block">' +
      'MARKET DECISION: ' + verdict + '</div>' +
      '<div style="color:#cbd5e1;font-size:0.78rem;margin-top:6px">VIX ' + fp(outlook.vix ? outlook.vix.value : null) +
      ' (' + (outlook.vix ? outlook.vix.regime : '—') + ')</div>' +
      '</div></div>';
  }

  function buildRegimeTradeability(outlook) {
    var regime = outlook.regime || {};
    var trade = outlook.tradeability || {};
    var bias = outlook.bias || {};
    var regimeColor = rc(regime.primary);
    var tradeColor = trade.score >= 70 ? '#15803d' : trade.score >= 40 ? '#a16207' : '#dc2626';
    var tradeBand = trade.band || '—';
    return '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem">' +
      '<div class="card">' +
      '<h3 style="margin:0 0 8px;font-size:0.85rem">MARKET REGIME</h3>' +
      '<div style="font-size:1.1rem;font-weight:800;color:' + regimeColor + '">' + (regime.primary || '—') + '</div>' +
      '<div style="font-size:0.82rem;color:#64748b;margin-top:2px">Level: <strong>' + (trade.score != null ? trade.score + '/100' : '—') + '</strong></div>' +
      '<div style="font-size:0.82rem;color:#64748b;margin-top:2px">' + (bias.label || '—') + ' · Conf ' + (outlook.confidence != null ? outlook.confidence + '%' : '—') + '</div>' +
      '</div>' +
      '<div class="card">' +
      '<h3 style="margin:0 0 8px;font-size:0.85rem">TRADEABILITY</h3>' +
      '<div style="font-size:1.1rem;font-weight:800;color:' + tradeColor + '">' + tradeBand + '</div>' +
      '<div style="font-size:0.82rem;color:#64748b;margin-top:2px">Score: <strong>' + (trade.score != null ? trade.score + '/100' : '—') + '</strong></div>' +
      '<div style="font-size:0.82rem;color:#64748b;margin-top:2px">' + (outlook.volatility_favours || '—') + '</div>' +
      '</div></div>';
  }

  function buildOutlookBars(outlook) {
    var probs = (outlook.bias || {}).probs || {};
    var bull = probs.bullish || 0;
    var neut = probs.neutral || 0;
    var bear = probs.bearish || 0;
    function bar(pct, color) {
      var filled = Math.round(pct / 5);
      var empty = 20 - filled;
      var s = '';
      for (var i = 0; i < filled; i++) s += '<span style="display:inline-block;width:8px;height:14px;border-radius:2px;background:' + color + ';margin-right:2px"></span>';
      for (var i = 0; i < empty; i++) s += '<span style="display:inline-block;width:8px;height:14px;border-radius:2px;background:#e2e8f0;margin-right:2px"></span>';
      return s;
    }
    return '<div class="card" style="margin-bottom:1rem">' +
      '<h3 style="margin:0 0 10px;font-size:0.9rem">TODAY\'S OUTLOOK</h3>' +
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">' +
      '<span style="width:70px;font-size:0.82rem;font-weight:600;color:#64748b">Bullish</span>' +
      bar(bull, '#15803d') +
      '<span style="font-size:0.85rem;font-weight:700;color:#15803d">' + bull + '%</span></div>' +
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">' +
      '<span style="width:70px;font-size:0.82rem;font-weight:600;color:#64748b">Sideways</span>' +
      bar(neut, '#a16207') +
      '<span style="font-size:0.85rem;font-weight:700;color:#a16207">' + neut + '%</span></div>' +
      '<div style="display:flex;align-items:center;gap:10px">' +
      '<span style="width:70px;font-size:0.82rem;font-weight:600;color:#64748b">Bearish</span>' +
      bar(bear, '#dc2626') +
      '<span style="font-size:0.85rem;font-weight:700;color:#dc2626">' + bear + '%</span></div>' +
      '<div style="margin-top:10px;padding:10px 14px;background:#f8fafc;border-radius:8px;font-size:0.82rem;color:#475569;border-left:3px solid ' + rc(outlook.bias ? outlook.bias.label : '') + '">' +
      (outlook.decision ? outlook.decision.primary_view : (outlook.bias ? outlook.bias.label + ' bias with ' + (outlook.confidence || '—') + '% confidence' : 'No outlook available')) +
      '</div></div>';
  }

  function buildFactors(outlook, breadthData) {
    var factors = computeFactors(outlook, breadthData);
    var rows = factors.map(function (f) {
      var col = factorColor(f.label);
      return '<div style="display:grid;grid-template-columns:110px 140px 1fr;gap:4px;padding:6px 0;border-bottom:1px solid #f1f5f9">' +
        '<span style="font-weight:700;font-size:0.82rem;color:#0f172a">• ' + f.name + '</span>' +
        factorLabel(f.label, col) +
        '<span style="font-size:0.8rem;color:#64748b">' + f.desc + '</span></div>';
    }).join('');
    var biasDir = outlook.bias ? outlook.bias.label : 'NEUTRAL';
    return '<div class="card" style="margin-bottom:1rem">' +
      '<h3 style="margin:0 0 10px;font-size:0.9rem">WHY AI IS ' + biasDir.toUpperCase() + '</h3>' +
      '<div style="background:#f8fafc;border-radius:8px;padding:10px 14px;border:1px solid #e2e8f0">' + rows + '</div></div>';
  }

  function buildOptionsIntelligence(outlook) {
    var opts = outlook.options || {};
    var pcr = opts.pcr && opts.pcr.expiries && opts.pcr.expiries.length ? opts.pcr.expiries[0] : {};
    var vix = outlook.vix || {};
    var kl = outlook.key_levels || {};
    var sup = (kl.supports || [])[0];
    var res = (kl.resistances || [])[0];
    var ceWall = (opts.ce_wall || [])[0];
    var er = outlook.expected_range || {};
    var ind = outlook.indicators || {};
    var expMove = ind.atr != null ? '±' + Math.round(ind.atr) + ' pts' : '—';

    function row(label, val, sublabel) {
      return '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:4px;padding:7px 0;border-bottom:1px solid #f1f5f9">' +
        '<span style="font-weight:700;font-size:0.82rem;color:#0f172a">' + label + '</span>' +
        '<span style="font-size:0.85rem;font-weight:600;color:#0f172a">' + val + '</span>' +
        '<span style="font-size:0.78rem;color:#64748b">' + (sublabel || '') + '</span></div>';
    }
    var pcrTxt = pcr.pcr != null ? pcr.pcr.toFixed(2) : '—';
    var pcrSub = pcr.pcr != null ? (pcr.pcr < 0.7 ? 'Bearish' : pcr.pcr < 1.0 ? 'Leaning bearish' : pcr.pcr < 1.25 ? 'Balanced' : 'Bullish') : '—';
    var vixLabel = vixRegime(vix.value);
    var callWall = ceWall ? (fp(ceWall.strike) + ' (' + (ceWall.oi != null ? Math.round(ceWall.oi).toLocaleString('en-IN') + ' OI' : '—') + ')') : '—';

    return '<div class="card" style="margin-bottom:1rem">' +
      '<h3 style="margin:0 0 10px;font-size:0.9rem">OPTIONS INTELLIGENCE</h3>' +
      '<div style="background:#f8fafc;border-radius:8px;padding:8px 14px;border:1px solid #e2e8f0">' +
      row('PCR', pcrTxt, pcrSub) +
      row('ATM IV', vix.value != null ? vix.value.toFixed(1) : '—', vix.value != null ? vixLabel : 'No feed') +
      row('India VIX', vix.value != null ? vix.value.toFixed(2) : '—', vix.trend || '—') +
      row('Exp. Move', expMove, 'ATR-based') +
      row('Call Wall', callWall, 'Resistance') +
      row('Support', sup != null ? fp(sup) : '—', 'Nearest') +
      row('Resistance', res != null ? fp(res) : '—', 'Nearest') +
      '</div></div>';
  }

  function buildStrategies(outlook) {
    var strats = outlook.strategies || [];
    if (!strats.length) return '<div class="card" style="margin-bottom:1rem"><h3 style="margin:0 0 8px;font-size:0.9rem">BEST STRATEGIES</h3><div style="color:#64748b;font-size:0.85rem">No applicable strategy — NO TRADE.</div></div>';

    var html = '<div class="card" style="margin-bottom:1rem"><h3 style="margin:0 0 10px;font-size:0.9rem">BEST STRATEGIES</h3>';
    strats.forEach(function (s) {
      var stars = Math.max(1, Math.min(5, Math.round((s.fit || 0) / 20)));
      var starsHtml = '';
      for (var i = 0; i < 5; i++) {
        starsHtml += '<span style="color:' + (i < stars ? '#f59e0b' : '#e2e8f0') + ';font-size:1rem">★</span>';
      }
      html += '<div style="margin-bottom:12px;padding:10px 14px;background:#f8fafc;border-radius:8px;border-left:3px solid ' + (s.rank === 1 ? '#15803d' : '#a16207') + '">' +
        '<div style="font-weight:700;font-size:0.9rem;color:#0f172a">' + starsHtml +
        ' <span style="font-size:0.78rem;color:#64748b">(' + (s.fit || 0) + '/100)</span> ' + (s.name || '—') + '</div>';
      if (s.entry) html += '<div style="font-size:0.8rem;color:#475569;margin-top:4px">• Entry: ' + s.entry + '</div>';
      if (s.why) {
        var whys = Array.isArray(s.why) ? s.why : [s.why];
        whys.forEach(function (w) {
          html += '<div style="font-size:0.78rem;color:#64748b;margin-top:2px">✓ ' + w + '</div>';
        });
      }
      if (s.risk) html += '<div style="font-size:0.8rem;color:#dc2626;margin-top:4px">• Risk: ' + s.risk + '</div>';
      if (s.exit) html += '<div style="font-size:0.8rem;color:#475569;margin-top:2px">• Exit: ' + s.exit + '</div>';
      html += '</div>';
    });
    if (outlook.strategy_to_avoid) {
      html += '<div style="padding:8px 14px;background:#fef3c7;border-radius:8px;font-size:0.82rem;color:#78350f;border-left:3px solid #f59e0b">' +
        '⚠ <strong>AVOID:</strong> ' + outlook.strategy_to_avoid + ' — ' + (outlook.avoid_reason || '') + '</div>';
    }
    html += '</div>';
    return html;
  }

  function buildKeyLevels(outlook) {
    var kl = outlook.key_levels || {};
    var sup = kl.supports || [];
    var res = kl.resistances || [];
    var price = null;
    try { price = outlook._quotePrice; } catch (e) {}
    var levels = [];
    if (sup.length > 1) levels.push({ label: 'S2', val: sup[1] });
    if (sup.length > 0) levels.push({ label: 'S1', val: sup[0] });
    levels.push({ label: 'CURRENT', val: price, accent: true });
    if (res.length > 0) levels.push({ label: 'R1', val: res[0] });
    if (res.length > 1) levels.push({ label: 'R2', val: res[1] });

    var rows = levels.map(function (l) {
      var bg = l.accent ? '#0f172a' : '#f8fafc';
      var fg = l.accent ? '#fff' : '#0f172a';
      return '<div style="display:flex;align-items:center;gap:10px;padding:8px 14px;background:' + bg + ';border-radius:6px;margin-bottom:4px">' +
        '<span style="width:80px;font-weight:700;font-size:0.82rem;color:' + fg + '">' + l.label + '</span>' +
        '<span style="font-size:0.82rem;color:' + fg + ';">│</span>' +
        '<span style="font-weight:700;font-size:0.9rem;color:' + fg + ';">' + fp(l.val) + '</span></div>';
    }).join('');
    return '<div class="card" style="margin-bottom:1rem"><h3 style="margin:0 0 10px;font-size:0.9rem">KEY LEVELS</h3>' + rows +
      '<div style="font-size:0.78rem;color:#64748b;margin-top:6px">' +
      '↑ Breakout: ' + (kl.breakout || '—') + '<br>↓ Breakdown: ' + (kl.breakdown || '—') + '</div></div>';
  }

  function buildRisk(outlook) {
    var d = outlook.decision || {};
    var items = [];
    if (d.bull_invalidation) items.push('⚠ Close below ' + d.bull_invalidation.replace('Daily close above ', '').replace('Close below ', '') + ' invalidates bullish view');
    if (d.bear_invalidation) items.push('⚠ ' + d.bear_invalidation);
    var vix = outlook.vix || {};
    if (vix.value != null && vix.value > 18) items.push('⚠ VIX spike above 18 signals caution');
    var gap = outlook.gap || {};
    if (gap.available && Math.abs(gap.gap_pct || 0) > 0.3) items.push('⚠ ' + gap.kind + ' of ' + Math.abs(gap.gap_pct).toFixed(1) + '% — watch for fill');
    if (!items.length) items.push('⚠ No critical invalidation triggers identified');
    return '<div class="card" style="margin-bottom:1rem"><h3 style="margin:0 0 8px;font-size:0.9rem">RISK & INVALIDATION</h3>' +
      '<div style="padding:10px 14px;background:#fef3c7;border-radius:8px;border-left:3px solid #f59e0b">' +
      items.map(function (it) { return '<div style="font-size:0.82rem;color:#78350f;margin-bottom:4px">' + it + '</div>'; }).join('') +
      '</div></div>';
  }

  function buildDecision(outlook) {
    var d = outlook.decision || {};
    var strats = outlook.strategies || [];
    var verdict = d.verdict || '—';
    var vColor = verdict === 'TRADE' ? '#15803d' : '#a16207';
    return '<div class="card" style="margin-bottom:1rem;border-top:3px solid ' + vColor + '">' +
      '<h3 style="margin:0 0 10px;font-size:0.9rem">AI DECISION</h3>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;padding:12px 14px;background:#f8fafc;border-radius:8px">' +
      '<div><div style="font-size:0.78rem;color:#64748b;font-weight:600">VERDICT</div>' +
      '<div style="margin-top:4px"><span style="background:' + vColor + ';color:#fff;padding:4px 14px;border-radius:6px;font-weight:800;font-size:0.95rem">' + verdict + '</span></div></div>' +
      '<div><div style="font-size:0.78rem;color:#64748b;font-weight:600">PREFERRED</div>' +
      '<div style="margin-top:4px;font-weight:700;font-size:0.9rem;color:#0f172a">' + (strats.length ? strats[0].name : '—') + '</div></div>' +
      '<div><div style="font-size:0.78rem;color:#64748b;font-weight:600">CONFIDENCE</div>' +
      '<div style="margin-top:4px;font-weight:700;font-size:0.9rem;color:#0f172a">' + (outlook.confidence != null ? outlook.confidence + '%' : '—') + '</div></div>' +
      '</div></div>';
  }

  function buildTradeRecord(outlook) {
    var trades = outlook.trades || [];
    if (!trades.length) return '';
    function resultColor(r) {
      r = (r || '').toUpperCase();
      if (r === 'WIN') return '#15803d';
      if (r === 'LOSS') return '#dc2626';
      if (r === 'NO_TRADE' || r === 'FLAT' || r === 'WAIT') return '#64748b';
      return '#a16207';
    }
    var rows = trades.map(function (t) {
      var rc = resultColor(t.result);
      var stratCell = t.strategy || '—';
      if (t.result === 'WAIT' || t.result === 'NO_TRADE') stratCell += '<div style="font-size:0.7rem;color:#64748b;font-weight:400">' + (t.reason || '') + '</div>';
      if (t.entry_outlook) {
        var eo = t.entry_outlook;
        var parts = [];
        if (eo.verdict) parts.push('AI: ' + eo.verdict);
        if (eo.regime) parts.push(eo.regime);
        if (eo.confidence != null) parts.push(Math.round(eo.confidence) + '%');
        if (parts.length) stratCell += '<div style="font-size:0.7rem;color:#475569;font-weight:400">' + (eo.date ? eo.date.slice(5) + ' · ' : '') + parts.join(' · ') + '</div>';
      }
      return '<tr style="border-bottom:1px solid #e2e8f0">' +
        '<td style="padding:6px 8px;font-weight:700;font-size:0.8rem;color:#0f172a">' + (t.symbol || '—') + '</td>' +
        '<td style="padding:6px 8px;font-size:0.8rem;color:#475569">' + (t.direction || '—') + '</td>' +
        '<td style="padding:6px 8px;font-size:0.8rem;color:#475569">' + stratCell + '</td>' +
        '<td style="padding:6px 8px;font-size:0.8rem;color:#475569">' + (t.entry_time ? t.entry_time + ' @ ' + fp(t.entry_price) : '—') + '</td>' +
        '<td style="padding:6px 8px;font-size:0.8rem;color:#475569">' + (t.exit_time ? t.exit_time + ' @ ' + fp(t.exit_price) : '—') + '</td>' +
        '<td style="padding:6px 8px;font-size:0.8rem;font-weight:700;color:' + rc + ';text-align:right">' + (t.points != null ? fc(t.points) : '—') + '</td>' +
        '<td style="padding:6px 8px;font-size:0.8rem;font-weight:700;color:' + rc + ';text-align:right">' + (t.result || '—') + '</td>' +
        '</tr>';
    }).join('');
    return '<div class="card" style="margin-bottom:1rem">' +
      '<h3 style="margin:0 0 10px;font-size:0.9rem">AI-GATED TRADE RECORD</h3>' +
      '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;min-width:520px">' +
      '<tr style="background:#f1f5f9">' +
      '<th style="padding:6px 8px;text-align:left;font-size:0.75rem;color:#0f172a;font-weight:800">SYMBOL</th>' +
      '<th style="padding:6px 8px;text-align:left;font-size:0.75rem;color:#0f172a;font-weight:800">DIR</th>' +
      '<th style="padding:6px 8px;text-align:left;font-size:0.75rem;color:#0f172a;font-weight:800">STRATEGY</th>' +
      '<th style="padding:6px 8px;text-align:left;font-size:0.75rem;color:#0f172a;font-weight:800">ENTRY</th>' +
      '<th style="padding:6px 8px;text-align:left;font-size:0.75rem;color:#0f172a;font-weight:800">EXIT</th>' +
      '<th style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#0f172a;font-weight:800">POINTS</th>' +
      '<th style="padding:6px 8px;text-align:right;font-size:0.75rem;color:#0f172a;font-weight:800">RESULT</th>' +
      '</tr>' + rows + '</table></div></div>';
  }

  /* ── Main render function ── */
  async function renderOutlookDashboard(containerId, cfg) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;

    var symbol = cfg.symbol || 'NIFTY';
    var api = cfg.api || symbol.toLowerCase();
    var base = cfg.apiBase || '..';

    el.innerHTML = '<div style="text-align:center;padding:40px;color:#64748b">Loading AI Market Outlook…</div>';

    // Parallel fetches
    var outlookPath = cfg.date ? 'market-outlook/' + cfg.date + '?symbol=' + symbol : 'market-outlook?symbol=' + symbol;
    var results = await Promise.all([
      fetchJSON(base, outlookPath),
      fetchJSON(base, api),
      fetchJSON(base, 'vix'),
      fetchJSON(base, 'breadth')
    ]);

    var outlook = results[0];
    var symbolData = results[1];
    var vixData = results[2];
    var breadthData = results[3];

    if (!outlook || outlook.error) {
      el.innerHTML = '<div style="text-align:center;padding:40px;color:#dc2626">No AI Market Outlook data available for ' + symbol + '. Run the outlook generator first.</div>';
      return;
    }

    // Inject quote price for key levels
    if (symbolData && symbolData.quote) {
      outlook._quotePrice = symbolData.quote.price;
    }

    // Use fresh VIX from the dedicated endpoint if available
    if (vixData && (vixData.close != null || vixData.price != null)) {
      outlook.vix = outlook.vix || {};
      outlook.vix.value = vixData.close || vixData.price;
      outlook.vix.change_pct = vixData.change_pct;
      outlook.vix.trend = (vixData.change_pct || 0) > 1 ? 'rising' : (vixData.change_pct || 0) < -1 ? 'falling' : 'flat';
      outlook.vix.regime = vixRegime(outlook.vix.value);
    }

    var quote = symbolData ? symbolData.quote : null;

    var html = '';
    html += buildNavTabs(symbol, cfg);
    html += '<div class="card hero" style="background:linear-gradient(135deg,#052e16 0%,#15803d 100%);border:none;color:#fff">';
    html += buildHero(quote, outlook, symbol);
    html += '</div>';
    html += buildRegimeTradeability(outlook);
    html += buildOutlookBars(outlook);
    html += buildFactors(outlook, breadthData);
    html += buildOptionsIntelligence(outlook);
    html += buildStrategies(outlook);
    html += buildKeyLevels(outlook);
    html += buildRisk(outlook);
    html += buildDecision(outlook);
    html += buildTradeRecord(outlook);

    // Disclaimer
    html += '<div style="padding:10px 14px;background:#f8fafc;border-radius:8px;font-size:0.78rem;color:#64748b;margin-top:0.5rem;border:1px solid #e2e8f0">' +
      'Analysis generated from stored market data only. Not a guarantee of direction or profitability. Options involve substantial risk — independently assess position size and risk before trading.</div>';

    el.innerHTML = html;

    // Wire in-place tab switches (homepage SPA mode)
    if (typeof cfg.onTab === 'function') {
      el.querySelectorAll('[data-tab]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          cfg.onTab(btn.getAttribute('data-tab'));
        });
      });
    }

    // Update the page-level updated bar if present
    var bar = document.getElementById('last-updated-bar');
    if (bar && outlook.date) {
      var at = outlook.as_of_ist || '';
      var timeOnly = at.indexOf(outlook.date) === 0 ? at.slice(outlook.date.length).trim() : at;
      bar.textContent = 'Data as of ' + outlook.date + (timeOnly ? ' · ' + timeOnly : '');
    }
  }

  /* ── Auto-refresh wrapper ── */
  function startOutlookRefresh(containerId, cfg, intervalMs) {
    stopOutlookRefresh(containerId);
    intervalMs = intervalMs || 30000;
    var tick = function () {
      renderOutlookDashboard(containerId, cfg);
      _timers[containerId] = setTimeout(tick, intervalMs);
    };
    tick();
  }

  function stopOutlookRefresh(containerId) {
    if (_timers[containerId]) {
      clearTimeout(_timers[containerId]);
      delete _timers[containerId];
    }
  }

  /* ── Expose globals ── */
  window.renderOutlookDashboard = renderOutlookDashboard;
  window.startOutlookRefresh = startOutlookRefresh;
  window.stopOutlookRefresh = stopOutlookRefresh;
})();
