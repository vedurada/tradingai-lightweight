const API_BASE = '';

async function fetchJSON(path) {
  try {
    const res = await fetch(`${API_BASE}/data/${path}.json`);
    if (!res.ok) throw new Error('Not found');
    return await res.json();
  } catch {
    return null;
  }
}

function formatPrice(p) {
  return p != null ? p.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '-';
}

function formatChange(p) {
  if (p == null) return '-';
  return (p >= 0 ? '+' : '') + p.toFixed(2);
}

function regimeColor(regime) {
  if (!regime) return '#94a3b8';
  const r = regime.toUpperCase();
  if (r.includes('BULLISH')) return '#22c55e';
  if (r.includes('BEARISH')) return '#ef4444';
  if (r.includes('RANGE')) return '#eab308';
  if (r.includes('VOLATILITY')) return '#f97316';
  return '#94a3b8';
}

function populateQuote(el, quote) {
  if (!quote) return;
  el.innerHTML = `
    <div class="price">${formatPrice(quote.price)}</div>
    <div style="color:${quote.change >= 0 ? '#22c55e' : '#ef4444'}">${formatChange(quote.change)} (${formatChange(quote.change_pct)}%)</div>
    <div class="status">Open: ${formatPrice(quote.open)} | High: ${formatPrice(quote.high)} | Low: ${formatPrice(quote.low)}</div>
    <div class="status">Prev Close: ${formatPrice(quote.previous_close)} | Vol: ${(quote.volume || 0).toLocaleString()}</div>
  `;
}

function populateRegime(el, regime) {
  if (!regime) return;
  el.innerHTML = `
    <span class="badge" style="background:${regimeColor(regime.regime)}20;color:${regimeColor(regime.regime)}">${regime.regime || 'N/A'}</span>
    <div class="status">Confidence: ${regime.confidence || 'N/A'}%</div>
    <div class="status">Trend: ${regime.trend || 'N/A'} | Momentum: ${regime.momentum || 'N/A'}</div>
  `;
}

function populateAI(el, ai) {
  if (!ai) return;
  el.innerHTML = `
    <h3>AI Outlook</h3>
    <p>${ai.market_summary || 'N/A'}</p>
    <div class="status">Trend: ${ai.trend_analysis || 'N/A'}</div>
    <div class="status">Momentum: ${ai.momentum_analysis || 'N/A'}</div>
    <div class="status">Volatility: ${ai.volatility_analysis || 'N/A'}</div>
    <div class="status">Confidence: ${ai.confidence || 'N/A'}%</div>
  `;
}

function populateStrategy(el, strategy) {
  if (!strategy || !strategy.strategies) return;
  const s = strategy.strategies[0];
  el.innerHTML = `
    <h3>Strategy</h3>
    <div class="status">${s.strategy || 'N/A'}</div>
    <div class="status">Condition: ${s.market_condition || 'N/A'}</div>
    <div class="status">Expiry: ${s.expiry || 'N/A'}</div>
    <div class="status">Entry: ${s.entry_trigger || 'N/A'}</div>
    <div class="status">Stop Loss: ${s.stop_loss || 'N/A'}</div>
    <div class="status">Target: ${s.target || 'N/A'}</div>
  `;
}

function populateScenarios(el, scenarios) {
  if (!scenarios) return;
  el.innerHTML = `
    <div class="card">
      <h3>Bullish</h3>
      <div class="status">${scenarios.bullish?.trigger || 'N/A'}</div>
      <div class="status">Target: ${scenarios.bullish?.target || 'N/A'}</div>
    </div>
    <div class="card">
      <h3>Bearish</h3>
      <div class="status">${scenarios.bearish?.trigger || 'N/A'}</div>
      <div class="status">Target: ${scenarios.bearish?.target || 'N/A'}</div>
    </div>
    <div class="card">
      <h3>Range</h3>
      <div class="status">${scenarios.range?.condition || 'N/A'}</div>
      <div class="status">Strategy: ${scenarios.range?.strategy_environment || 'N/A'}</div>
    </div>
  `;
}

function populateOptions(el, options) {
  if (!options || options.data_unavailable) {
    el.innerHTML = '<div class="status">Options data unavailable</div>';
    return;
  }
  el.innerHTML = `
    <div class="status">PCR: ${options.pcr?.toFixed(3) || 'N/A'}</div>
    <div class="status">Call OI: ${(options.call_oi || 0).toLocaleString()} | Put OI: ${(options.put_oi || 0).toLocaleString()}</div>
    <div class="status">Max Pain: ${formatPrice(options.max_pain?.max_pain)}</div>
    <div class="status">IV Avg: ${options.iv_stats?.avg_iv || 'N/A'} | Rank: ${options.iv_stats?.iv_rank || 'N/A'}%</div>
    <div class="status">Environment: ${options.environment || 'N/A'}</div>
  `;
}

function populateIndicators(el, indicators) {
  if (!indicators) return;
  el.innerHTML = `
    <div class="status">VWAP: ${formatPrice(indicators.vwap)} | RSI: ${indicators.rsi?.toFixed(1) || 'N/A'}</div>
    <div class="status">MACD: ${indicators.macd?.macd?.toFixed(4) || 'N/A'} | ADX: ${indicators.adx?.toFixed(1) || 'N/A'}</div>
    <div class="status">EMA20: ${formatPrice(indicators.ema20)} | EMA50: ${formatPrice(indicators.ema50)}</div>
    <div class="status">Pivot: ${formatPrice(indicators.pivot?.pivot)} | BC: ${formatPrice(indicators.cpr?.bc)} | TC: ${formatPrice(indicators.cpr?.tc)}</div>
    <div class="status">Support: ${(indicators.support_resistance?.support || []).join(', ') || 'N/A'}</div>
    <div class="status">Resistance: ${(indicators.support_resistance?.resistance || []).join(', ') || 'N/A'}</div>
  `;
}

function setLastUpdated(ts) {
  const el = document.getElementById('last-updated');
  if (el && ts) {
    el.textContent = 'Last updated: ' + new Date(ts).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' });
  }
}

function showStale(data_quality) {
  if (data_quality === 'STALE' || data_quality === 'PARTIAL') {
    const el = document.getElementById('market-status');
    if (el) {
      el.innerHTML = `<span class="badge badge-yellow">${data_quality === 'STALE' ? 'STALE DATA' : 'PARTIAL DATA'}</span>`;
    }
  }
}