/*
 * phase41.js — TradingAI Phase 41 Frontend Integration Module
 *
 * Fetches and renders:
 *   - Trade Qualification (TRADE / WAIT / NO_TRADE)
 *   - Paper Trade Status (active, completed, PnL)
 *   - Market Evidence (directional, score, supporting rules)
 *   - Trade Qualification Checklist
 *
 * Usage:
 *   <div id="phase41-qualification"></div>
 *   <script src="/assets/js/phase41.js"></script>
 *   <script>renderPhase41Qualification('phase41-qualification', {symbol:'NIFTY'});</script>
 */
(function () {
  'use strict';

  var API_BASE = '/api';

  async function fetchAPI(path, method, body) {
    try {
      var opts = { method: method || 'GET', headers: {} };
      if (body) {
        opts.headers['Content-Type'] = 'application/json';
        opts.body = JSON.stringify(body);
      }
      var ts = Date.now();
      var res = await fetch(API_BASE + path + '?_=' + ts, opts);
      if (!res.ok) return null;
      var text = await res.text();
      try { return JSON.parse(text); } catch { return null; }
    } catch { return null; }
  }

  function setElement(el, html) {
    if (!el) return;
    el.innerHTML = html;
  }

  function statusBadge(text, type) {
    var colors = {
      TRADE: { bg: '#dcfce7', color: '#15803d' },
      WAIT: { bg: '#fef3c7', color: '#92400e' },
      NO_TRADE: { bg: '#fef2f2', color: '#991b1b' },
      LIVE: { bg: '#dcfce7', color: '#15803d' },
      STALE: { bg: '#fef3c7', color: '#92400e' },
      UNAVAILABLE: { bg: '#f1f5f9', color: '#64748b' },
      ERROR: { bg: '#fef2f2', color: '#991b1b' },
      BULLISH: { bg: '#dcfce7', color: '#15803d' },
      BEARISH: { bg: '#fef2f2', color: '#991b1b' },
      RANGE: { bg: '#fef3c7', color: '#92400e' },
      MIXED: { bg: '#f1f5f9', color: '#64748b' },
    };
    var c = colors[type] || colors.UNAVAILABLE;
    return '<span style="display:inline-block;padding:2px 10px;border-radius:4px;font-size:0.78rem;font-weight:700;background:' + c.bg + ';color:' + c.color + '">' + text + '</span>';
  }

  function formatPrice(p) {
    if (p == null) return '—';
    return p.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }

  async function loadQualification(symbol) {
    var data = await fetchAPI('/trade-qualification', 'POST', {
      instrument: symbol,
      snapshot: { close: 0 },
      evidence: { overall: {} },
      market_state: {},
      outlook: { bias: 'NEUTRAL', trade_state: 'NO_TRADE' }
    });
    return data;
  }

  async function loadPaperTrades(symbol) {
    var data = await fetchAPI('/paper-trades' + (symbol ? '?instrument=' + symbol : ''));
    return data;
  }

  async function loadActivePaperTrades(symbol) {
    var data = await fetchAPI('/paper-trades/active');
    return data;
  }

  async function loadMarketEvidence(symbol) {
    var data = await fetchAPI('/market-evidence/' + symbol);
    return data;
  }

  /* ── Render Qualification Checklist ── */
  async function renderQualificationChecklist(containerId, symbol) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;
    setElement(el, '<div style="text-align:center;padding:8px;color:#64748b;font-size:0.85rem">Loading qualification…</div>');

    var result = await loadQualification(symbol);
    if (!result || !result.data) {
      setElement(el, '<div style="padding:8px;color:#94a3b8;font-size:0.85rem">Qualification: Data unavailable</div>');
      return;
    }

    var d = result.data;
    var status = d.trade_status || 'NO_TRADE';
    var checks = d.checks || {};
    var reason = d.reason || '';
    var strategy = d.strategy || null;
    var direction = d.direction || 'NEUTRAL';

    var checkNames = {
      ai_outlook_present: 'AI outlook present',
      ai_bias_valid: 'AI bias valid',
      ai_trade_state_valid: 'AI trade state valid',
      ai_trade_state_requires_trade: 'AI requires TRADE state',
      ai_confidence_reviewed: 'AI confidence reviewed',
      evidence_available: 'Evidence available',
      evidence_directional: 'Evidence directional',
      evidence_no_severe_conflict: 'No severe conflict',
      evidence_sufficient_groups: 'Sufficient evidence groups',
      bullish_confirmation: 'Bullish confirmation',
      bearish_confirmation: 'Bearish confirmation',
      range_confirmation: 'Range confirmation',
      confirmation_not_required: 'Confirmation not required',
      invalidation_defined: 'Invalidation defined',
      risk_calculable: 'Risk calculable',
      risk_reward_acceptable: 'Risk/reward acceptable',
      risk_within_limits: 'Risk within limits',
      options_data_available: 'Options data available',
      options_not_required: 'Options not required',
      core_data_available: 'Core data available',
      no_active_trade_exists: 'No active trade',
      daily_risk_available: 'Daily risk available',
    };

    var checklistHtml = '';
    for (var key in checkNames) {
      if (!checks[key]) continue;
      var passed = checks[key].passed;
      var detail = checks[key].detail || '';
      var icon = passed ? '✓' : '✗';
      var color = passed ? '#15803d' : '#dc2626';
      checklistHtml += '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:0.78rem;color:' + color + '">' +
        '<span style="font-weight:700;width:16px">' + icon + '</span>' +
        '<span>' + checkNames[key] + '</span>' +
        '<span style="color:#64748b;font-size:0.72rem;margin-left:auto">' + detail + '</span></div>';
    }

    var statusColor = status === 'TRADE' ? '#15803d' : status === 'WAIT' ? '#eab308' : '#dc2626';
    var statusBg = status === 'TRADE' ? '#dcfce7' : status === 'WAIT' ? '#fef3c7' : '#fef2f2';

    var html = '<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;background:#fff">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">' +
      '<h3 style="margin:0;font-size:0.85rem;font-weight:700;color:#0f172a">TRADE QUALIFICATION</h3>' +
      '<span style="padding:3px 10px;border-radius:4px;font-size:0.82rem;font-weight:800;background:' + statusColor + ';color:#fff">' + status.replace(/_/g, ' ') + '</span>' +
      '</div>' +
      '<div style="font-size:0.72rem;color:#64748b;margin-bottom:6px">' + (reason || 'Loading…') + '</div>' +
      '<div style="font-size:0.78rem;line-height:1.5">' + checklistHtml + '</div>';

    if (status === 'TRADE' && strategy) {
      html += '<div style="margin-top:8px;padding-top:8px;border-top:1px solid #f1f5f9">' +
        '<div style="font-size:0.78rem;font-weight:700;color:#0f172a">Strategy: ' + strategy + '</div>' +
        '<div style="font-size:0.72rem;color:#64748b">Direction: ' + direction + '</div></div>';
    }

    html += '</div>';
    setElement(el, html);
  }

  /* ── Render Paper Trade Status ── */
  async function renderPaperTradeStatus(containerId, symbol) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;
    setElement(el, '<div style="text-align:center;padding:8px;color:#64748b;font-size:0.85rem">Loading paper trade status…</div>');

    var data = await loadActivePaperTrades(symbol);
    var html = '';

    if (!data || !data.success || !data.data || data.data.count === 0) {
      html = '<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;background:#fff">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
        '<h3 style="margin:0;font-size:0.85rem;font-weight:700;color:#0f172a">PAPER TRADE</h3>' +
        statusBadge('NO ACTIVE', 'UNAVAILABLE') +
        '</div>' +
        '<div style="font-size:0.78rem;color:#64748b">No active paper trade. Qualification required to create one.</div>' +
        '<div style="font-size:0.72rem;color:#94a3b8;margin-top:4px">PAPER TRADE — NO BROKER ORDER IS PLACED</div></div>';
    } else {
      var trades = data.data.trades || [];
      var trade = trades[0];
      var pnl = trade.pnl;
      var pnlColor = pnl > 0 ? '#15803d' : pnl < 0 ? '#dc2626' : '#64748b';
      var pnlStr = pnl != null ? (pnl >= 0 ? '+' : '') + pnl.toFixed(2) : '—';
      html = '<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;background:#fff">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px">' +
        '<h3 style="margin:0;font-size:0.85rem;font-weight:700;color:#0f172a">PAPER TRADE</h3>' +
        statusBadge(trade.status || 'ACTIVE', trade.status === 'ACTIVE' ? 'LIVE' : 'UNAVAILABLE') +
        '</div>' +
        '<div style="font-size:0.78rem;color:#0f172a;margin-bottom:4px">ID: <span style="font-family:monospace;font-size:0.75rem">' + (trade.trade_id || '—') + '</span></div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.78rem;color:#64748b">' +
        '<div>Entry: ' + formatPrice(trade.entry_price) + '</div>' +
        '<div>Exit: ' + formatPrice(trade.exit_price) + '</div>' +
        '<div>Stop: ' + formatPrice(trade.stop) + '</div>' +
        '<div>Target: ' + formatPrice(trade.target) + '</div>' +
        '<div>Direction: ' + (trade.direction || '—') + '</div>' +
        '<div>P&L: <span style="color:' + pnlColor + ';font-weight:700">' + pnlStr + '</span></div>' +
        '<div>Reason: ' + (trade.exit_reason || '—') + '</div>' +
        '<div>Status: ' + (trade.status || '—') + '</div></div>' +
        '<div style="font-size:0.72rem;color:#94a3b8;margin-top:6px">PAPER TRADE — NO BROKER ORDER IS PLACED</div></div>';
    }
    setElement(el, html);
  }

  /* ── Render Market Evidence ── */
  async function renderMarketEvidence(containerId, symbol) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;
    setElement(el, '<div style="text-align:center;padding:8px;color:#64748b;font-size:0.85rem">Loading evidence…</div>');

    var data = await loadMarketEvidence(symbol);
    if (!data || !data.data) {
      setElement(el, '<div style="padding:8px;color:#94a3b8;font-size:0.85rem">Evidence: Data unavailable</div>');
      return;
    }

    var evidence = data.data;
    var html = '<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;background:#fff">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">' +
      '<h3 style="margin:0;font-size:0.85rem;font-weight:700;color:#0f172a">MARKET EVIDENCE</h3>';

    if (evidence.overall) {
      var signal = evidence.overall.overall_signal || 'UNKNOWN';
      html += statusBadge(signal, signal);
    }
    html += '</div>';

    if (evidence.groups) {
      var groups = ['trend', 'momentum', 'vwap', 'structure', 'volatility', 'options', 'market_confirmation'];
      for (var i = 0; i < groups.length; i++) {
        var g = groups[i];
        var groupData = evidence.groups[g];
        if (!groupData) continue;
        var score = groupData.score || '—';
        var direction = groupData.direction || groupData.signal || '—';
        html += '<div style="font-size:0.78rem;padding:4px 0;border-bottom:1px solid #f1f5f9">' +
          '<span style="font-weight:700;color:#0f172a;text-transform:capitalize">' + g + '</span>: ' +
          '<span style="color:#64748b">' + direction + ' ' + score + '</span></div>';
      }
    }

    html += '<div style="font-size:0.72rem;color:#94a3b8;margin-top:6px">Deterministic evidence from market data — not an AI prediction</div></div>';
    setElement(el, html);
  }

  /* ── Render Trade Qualification (full panel) ── */
  async function renderTradeQualification(containerId, symbol) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;
    setElement(el, '<div style="text-align:center;padding:8px;color:#64748b;font-size:0.85rem">Loading qualification…</div>');

    var result = await loadQualification(symbol);
    if (!result || !result.data) {
      setElement(el, '<div style="padding:8px;color:#94a3b8;font-size:0.85rem">Qualification: Data unavailable</div>');
      return;
    }

    var d = result.data;
    var status = d.trade_status || 'NO_TRADE';
    var checks = d.checks || {};
    var reason = d.reason || '';
    var strategy = d.strategy || null;
    var direction = d.direction || 'NEUTRAL';
    var entryPrice = d.entry_price;
    var stopPrice = d.stop_price;
    var targetPrice = d.target_price;
    var riskReward = d.risk_reward;

    var checkNames = {
      ai_outlook_present: 'AI outlook present',
      ai_bias_valid: 'AI bias valid',
      ai_trade_state_valid: 'AI trade state valid',
      ai_trade_state_requires_trade: 'AI requires TRADE state',
      ai_confidence_reviewed: 'AI confidence reviewed',
      evidence_available: 'Evidence available',
      evidence_directional: 'Evidence directional',
      evidence_no_severe_conflict: 'No severe conflict',
      evidence_sufficient_groups: 'Sufficient evidence',
      bullish_confirmation: 'Bullish confirmation',
      bearish_confirmation: 'Bearish confirmation',
      range_confirmation: 'Range confirmation',
      confirmation_not_required: 'Confirmation not required',
      invalidation_defined: 'Invalidation defined',
      risk_calculable: 'Risk calculable',
      risk_reward_acceptable: 'Risk/reward acceptable',
      risk_within_limits: 'Risk within limits',
      options_data_available: 'Options data available',
      options_not_required: 'Options not required',
      core_data_available: 'Core data available',
      no_active_trade_exists: 'No active trade',
      daily_risk_available: 'Daily risk available',
    };

    var checklistHtml = '';
    for (var key in checkNames) {
      if (!checks[key]) continue;
      var passed = checks[key].passed;
      var detail = checks[key].detail || '';
      var icon = passed ? '✓' : '✗';
      var color = passed ? '#15803d' : '#dc2626';
      checklistHtml += '<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:0.78rem;color:' + color + '">' +
        '<span style="font-weight:700;width:16px">' + icon + '</span>' +
        '<span>' + checkNames[key] + '</span>' +
        '<span style="color:#64748b;font-size:0.72rem;margin-left:auto">' + detail + '</span></div>';
    }

    var statusColor = status === 'TRADE' ? '#15803d' : status === 'WAIT' ? '#eab308' : '#dc2626';
    var statusBg = status === 'TRADE' ? '#dcfce7' : status === 'WAIT' ? '#fef3c7' : '#fef2f2';

    var html = '<div style="border:2px solid ' + statusColor + ';border-radius:8px;padding:12px 16px;background:' + statusBg + '">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">' +
      '<h3 style="margin:0;font-size:0.9rem;font-weight:800;color:#0f172a">TRADE QUALIFICATION</h3>' +
      '<span style="padding:4px 12px;border-radius:4px;font-size:0.9rem;font-weight:800;background:' + statusColor + ';color:#fff">' + status.replace(/_/g, ' ') + '</span>' +
      '</div>' +
      '<div style="font-size:0.78rem;color:#64748b;margin-bottom:8px">' + (reason || 'Loading…') + '</div>' +
      '<div style="font-size:0.78rem;line-height:1.6">' + checklistHtml + '</div>';

    if (status === 'TRADE') {
      html += '<div style="margin-top:10px;padding-top:10px;border-top:1px solid #e2e8f0">' +
        '<div style="font-size:0.82rem;font-weight:700;color:#0f172a;margin-bottom:4px">Strategy Parameters</div>' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.78rem;color:#64748b">' +
        '<div>Strategy: <strong>' + (strategy || '—') + '</strong></div>' +
        '<div>Direction: <strong>' + direction + '</strong></div>' +
        '<div>Entry: ' + formatPrice(entryPrice) + '</div>' +
        '<div>Stop: ' + formatPrice(stopPrice) + '</div>' +
        '<div>Target: ' + formatPrice(targetPrice) + '</div>' +
        '<div>R:R: ' + (riskReward != null ? riskReward.toFixed(2) : '—') + '</div></div></div>';
    }

    html += '<div style="font-size:0.72rem;color:#94a3b8;margin-top:8px">Frontend renders backend decisions only. No independent trading logic.</div></div>';
    setElement(el, html);
  }

  /* ── Render AI Outlook Summary ── */
  async function renderAIOutlook(containerId, symbol) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;
    setElement(el, '<div style="text-align:center;padding:8px;color:#64748b;font-size:0.85rem">Loading AI outlook…</div>');

    var data = await fetchAPI('/market-outlook?symbol=' + symbol);
    if (!data || !data.success || !data.data) {
      setElement(el, '<div style="padding:8px;color:#94a3b8;font-size:0.85rem">AI Outlook: Unavailable</div>');
      return;
    }

    var outlook = data.data;
    var bias = outlook.bias || {};
    var biasLabel = bias.label || 'NEUTRAL';
    var confidence = outlook.confidence || '—';
    var regime = outlook.regime || {};
    var regimePrimary = regime.primary || 'UNKNOWN';
    var summary = outlook.summary || outlook.market_summary || '—';
    var confirmation = outlook.confirmation_conditions || outlook.confirmation || '—';
    var invalidation = outlook.invalidation_conditions || outlook.invalidation || '—';

    var html = '<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;background:#fff">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">' +
      '<h3 style="margin:0;font-size:0.85rem;font-weight:700;color:#0f172a">AI OUTLOOK</h3>' +
      statusBadge(biasLabel, biasLabel) + '</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:0.78rem;color:#64748b;margin-bottom:6px">' +
      '<div>Confidence: <strong>' + confidence + (typeof confidence === 'number' ? '/100' : '') + '</strong></div>' +
      '<div>Regime: <strong>' + regimePrimary + '</strong></div></div>' +
      '<div style="font-size:0.78rem;color:#0f172a;margin-bottom:6px">' + summary + '</div>' +
      '<div style="font-size:0.72rem;color:#64748b;padding-top:6px;border-top:1px solid #f1f5f9">' +
      '<div>Confirmation: ' + confirmation + '</div>' +
      '<div>Invalidation: ' + invalidation + '</div></div>' +
      '<div style="font-size:0.72rem;color:#94a3b8;margin-top:6px">AI interpretation of market evidence — not a guaranteed prediction.</div></div>';
    setElement(el, html);
  }

  /* ── Render Paper Trade Table ── */
  async function renderPaperTradeTable(containerId, symbol) {
    var el = typeof containerId === 'string' ? document.getElementById(containerId) : containerId;
    if (!el) return;
    setElement(el, '<div style="text-align:center;padding:8px;color:#64748b;font-size:0.85rem">Loading paper trades…</div>');

    var data = await loadPaperTrades(symbol);
    if (!data || !data.success || !data.data) {
      setElement(el, '<div style="padding:8px;color:#94a3b8;font-size:0.85rem">Paper trades: Unavailable</div>');
      return;
    }

    var trades = data.data.trades || [];
    if (trades.length === 0) {
      setElement(el, '<div style="padding:8px;color:#94a3b8;font-size:0.85rem">No paper trades recorded</div>');
      return;
    }

    var html = '<div style="border:1px solid #e2e8f0;border-radius:8px;padding:10px 14px;background:#fff">' +
      '<h3 style="margin:0 0 8px;font-size:0.85rem;font-weight:700;color:#0f172a">PAPER TRADE HISTORY</h3>' +
      '<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse;font-size:0.75rem">' +
      '<tr style="background:#f8fafc">' +
      '<th style="padding:4px 6px;text-align:left;font-size:0.66rem;color:#64748b;text-transform:uppercase">Time</th>' +
      '<th style="padding:4px 6px;text-align:left;font-size:0.66rem;color:#64748b">Dir</th>' +
      '<th style="padding:4px 6px;text-align:left;font-size:0.66rem;color:#64748b">Entry</th>' +
      '<th style="padding:4px 6px;text-align:left;font-size:0.66rem;color:#64748b">Exit</th>' +
      '<th style="padding:4px 6px;text-align:right;font-size:0.66rem;color:#64748b">PnL</th>' +
      '<th style="padding:4px 6px;text-align:left;font-size:0.66rem;color:#64748b">Outcome</th>' +
      '</tr>';

    for (var i = 0; i < trades.length; i++) {
      var t = trades[i];
      var pnl = t.pnl;
      var pnlStr = pnl != null ? (pnl >= 0 ? '+' : '') + pnl.toFixed(2) : '—';
      var pnlColor = pnl > 0 ? '#15803d' : pnl < 0 ? '#dc2626' : '#64748b';
      html += '<tr>' +
        '<td style="padding:3px 6px;color:#0f172a">' + (t.entry_timestamp || '—') + '</td>' +
        '<td style="padding:3px 6px;color:#0f172a">' + (t.direction || '—') + '</td>' +
        '<td style="padding:3px 6px;color:#0f172a">' + formatPrice(t.entry_price) + '</td>' +
        '<td style="padding:3px 6px;color:#0f172a">' + formatPrice(t.exit_price) + '</td>' +
        '<td style="padding:3px 6px;text-align:right;color:' + pnlColor + ';font-weight:700">' + pnlStr + '</td>' +
        '<td style="padding:3px 6px;color:#0f172a">' + (t.outcome || '—') + '</td></tr>';
    }

    html += '</table></div>' +
      '<div style="font-size:0.72rem;color:#94a3b8;margin-top:6px">PAPER TRADE — NO BROKER ORDER IS PLACED</div></div>';
    setElement(el, html);
  }

  /* ── Expose globals ── */
  window.renderPhase41Qualification = renderTradeQualification;
  window.renderPhase41Checklist = renderQualificationChecklist;
  window.renderPhase41PaperTrade = renderPaperTradeStatus;
  window.renderPhase41PaperTable = renderPaperTradeTable;
  window.renderPhase41Evidence = renderMarketEvidence;
  window.renderPhase41Outlook = renderAIOutlook;
  window.loadPhase41Qualification = loadQualification;
  window.loadPhase41PaperTrades = loadPaperTrades;
  window.loadPhase41ActiveTrades = loadActivePaperTrades;
  window.loadPhase41MarketEvidence = loadMarketEvidence;
})();
