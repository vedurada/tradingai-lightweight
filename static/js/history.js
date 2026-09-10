async function loadHistory() {
  const grid = document.getElementById("history-grid");
  if (!grid) return;
  grid.innerHTML = '<div class="card">Loading history...</div>';

  const data = await fetchJSON("history");
  if (!data) {
    grid.innerHTML = '<div class="card">No history data yet</div>';
    return;
  }

  const symbols = Object.keys(data).sort();
  if (!symbols.length) {
    grid.innerHTML = '<div class="card">No history data yet</div>';
    return;
  }

  let totalEntries = 0, wins = 0, losses = 0, flats = 0, totalPoints = 0, countPoints = 0;
  for (const sym of symbols) {
    for (const e of data[sym]) {
      totalEntries++;
      if (e.result === 'WIN') wins++;
      else if (e.result === 'LOSS') losses++;
      else flats++;
      if (e.points != null) { totalPoints += e.points; countPoints++; }
    }
  }
  const winRate = totalEntries > 0 ? ((wins / totalEntries) * 100).toFixed(1) : 0;
  const avgPoints = countPoints > 0 ? (totalPoints / countPoints).toFixed(2) : 0;

  let html = `<div class="card" style="margin-bottom:1rem"><h3>Analytics</h3><div class="status">Total: ${totalEntries} | Wins: ${wins} | Losses: ${losses} | Flats: ${flats} | Win Rate: ${winRate}% | Avg Points: ${avgPoints}</div></div>`;

  for (const symbol of symbols) {
    const entries = data[symbol];
    for (const e of entries) {
      const pts = e.points != null ? e.points : '—';
      const res = e.result || 'OPEN';
      const rc = res === 'WIN' ? '#22c55e' : res === 'LOSS' ? '#ef4444' : '#94a3b8';
      const locked = e.locked_price ? formatPrice(e.locked_price) : '—';
      const closed = e.closed_price ? formatPrice(e.closed_price) : '—';
      html += `<div class="card" style="margin-bottom:0.5rem">
        <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:0.5rem">
          <strong>${symbol}</strong>
          <span style="color:${rc};font-weight:bold">${res}</span>
          <span>${e.date}</span>
          <span>${e.strategy || 'N/A'}</span>
          <span>${locked} → ${closed}</span>
          <span style="color:${rc}">${pts} pts</span>
          <span>${e.market_regime || 'N/A'} | ${e.directional_bias || 'N/A'}</span>
        </div>
        <details style="margin-top:0.5rem">
          <summary style="cursor:pointer;color:#22c55e">Details</summary>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:0.3rem;margin-top:0.5rem">
            <div>Conf: ${e.confidence || 'N/A'}%</div>
            <div>Evidence: ${e.evidence_strength || 'N/A'}</div>
            <div>Vol: ${e.volatility_classification || 'N/A'}</div>
            <div>Structure: ${e.market_structure || 'N/A'}</div>
            <div>Env: ${e.strategy_environment || 'N/A'}</div>
            <div>Invalidation: ${e.invalidation || 'N/A'}</div>
            <div>No-Trade: ${(e.no_trade_conditions || []).join(', ') || 'N/A'}</div>
            <div>Summary: ${e.market_summary || 'N/A'}</div>
          </div>
        </details>
      </div>`;
    }
  }

  grid.innerHTML = html;
  setLastUpdated(new Date().toISOString());
}

document.addEventListener('DOMContentLoaded', () => { loadHistory(); startDataRefresh(loadHistory); });