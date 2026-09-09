async function loadNifty() {
  const data = await fetchJSON('nifty');
  if (!data) return;

  const priceEl = document.getElementById('nifty-price');
  if (priceEl) priceEl.textContent = formatPrice(data.quote?.price);

  const regimeEl = document.getElementById('nifty-regime');
  if (regimeEl) regimeEl.innerHTML = `<span class="badge" style="background:${regimeColor(data.regime?.regime)}20;color:${regimeColor(data.regime?.regime)}">${data.regime?.regime || 'N/A'}</span>`;

  const outlookEl = document.getElementById('nifty-outlook');
  if (outlookEl && data.ai_outlook) {
    outlookEl.innerHTML = `<p>${data.ai_outlook.market_summary || 'N/A'}</p><div class="status">Bias: ${data.ai_outlook.directional_bias || 'N/A'} | Conf: ${data.ai_outlook.confidence || 'N/A'}% | Evidence: ${data.ai_outlook.evidence_strength || 'N/A'}</div><div class="status">Vol: ${data.ai_outlook.volatility_classification || 'N/A'} | Structure: ${data.ai_outlook.market_structure || 'N/A'}</div><div class="status">Env: ${data.ai_outlook.strategy_environment || 'N/A'} | Invalidation: ${data.ai_outlook.invalidation || 'N/A'}</div>`;
  }

  const outlookDetailEl = document.getElementById('nifty-outlook-detail');
  if (outlookDetailEl && data.ai_outlook) {
    const nt = (data.ai_outlook.no_trade_conditions || []).join(', ');
    outlookDetailEl.innerHTML = `<div class="status">No-Trade: ${nt || 'N/A'}</div>`;
  }

  const indicatorsEl = document.getElementById('nifty-indicators');
  if (indicatorsEl) populateIndicators(indicatorsEl, data.indicators);

  const scenariosEl = document.getElementById('nifty-scenarios');
  if (scenariosEl && data.scenarios) {
    scenariosEl.innerHTML = data.scenarios.map(s => `<div class="status">${s.scenario_type || 'N/A'}: ${s.description || 'N/A'} | Target: ${s.target || 'N/A'} | Stop: ${s.stop_loss || 'N/A'}</div>`).join('');
  }

  const strategyEl = document.getElementById('nifty-strategy');
  if (strategyEl && data.strategy) {
    const s = data.strategy.strategies?.[0];
    strategyEl.innerHTML = s ? `<div class="status">${s.strategy || 'N/A'}</div><div class="status">Entry: ${s.entry_trigger || 'N/A'} | Stop: ${s.stop_loss || 'N/A'} | Target: ${s.target || 'N/A'}</div>` : '';
  }

  const historyEl = document.getElementById('nifty-history');
  if (historyEl) {
    const histData = await fetchJSON('history');
    if (histData && histData.NIFTY) {
      const entries = histData.NIFTY.slice(0, 7);
      let html = '<h3>P&L History</h3><table class="history-table"><thead><tr><th>Date</th><th>Locked</th><th>Closed</th><th>Points</th><th>Result</th></tr></thead><tbody>';
      for (const e of entries) {
        const pts = e.points != null ? e.points : '—';
        const res = e.result || 'OPEN';
        const rc = res === 'WIN' ? '#22c55e' : res === 'LOSS' ? '#ef4444' : '#94a3b8';
        html += `<tr><td>${e.date}</td><td>${formatPrice(e.locked_price)}</td><td>${e.closed_price ? formatPrice(e.closed_price) : '—'}</td><td style="color:${rc};font-weight:bold">${pts}</td><td style="color:${rc}">${res}</td></tr>`;
      }
      html += '</tbody></table>';
      historyEl.innerHTML = html;
    }
  }

  const outlookHistEl = document.getElementById('nifty-outlook-history');
  if (outlookHistEl) {
    const histData = await fetchJSON('history');
    if (histData && histData.NIFTY) {
      const entries = histData.NIFTY.slice(0, 5);
      let html = '<h3>AI Outlook History</h3>';
      for (const e of entries) {
        const rc = e.result === 'WIN' ? '#22c55e' : e.result === 'LOSS' ? '#ef4444' : '#94a3b8';
        html += `<div class="card" style="margin-bottom:0.5rem">
          <div class="status">${e.date} | ${e.market_regime || 'N/A'} | Conf: ${e.confidence || 'N/A'}% | Evidence: ${e.evidence_strength || 'N/A'} | <span style="color:${rc}">${e.result || 'OPEN'}</span></div>
          <div class="status">Strategy: ${e.strategy || 'N/A'} | Bias: ${e.directional_bias || 'N/A'} | Vol: ${e.volatility_classification || 'N/A'} | Structure: ${e.market_structure || 'N/A'}</div>
          <div class="status">Env: ${e.strategy_environment || 'N/A'} | Invalidation: ${e.invalidation || 'N/A'}</div>
          <div class="status">${e.market_summary || ''}</div>
        </div>`;
      }
      outlookHistEl.innerHTML = html;
    }
  }

  setLastUpdated(data.last_updated);
}

document.addEventListener('DOMContentLoaded', () => { loadNifty(); startDataRefresh(loadNifty); });