async function loadDashboard() {
  const data = await fetchJSON('market');
  if (!data || !data.instruments) return;

  const grid = document.getElementById('market-grid');
  if (grid) {
    grid.innerHTML = '';
    for (const [symbol, inst] of Object.entries(data.instruments)) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <h3>${symbol}</h3>
        <div class="price">${formatPrice(inst.quote?.price)}</div>
        <div style="color:${inst.quote?.change >= 0 ? '#22c55e' : '#ef4444'}">${formatChange(inst.quote?.change)} (${formatChange(inst.quote?.change_pct)}%)</div>
        <span class="badge" style="background:${regimeColor(inst.regime?.regime)}20;color:${regimeColor(inst.regime?.regime)}">${inst.regime?.regime || 'N/A'}</span>
        <div class="status">Support: ${(inst.indicators?.support_resistance?.support || []).join(', ') || 'N/A'}</div>
        <div class="status">Resistance: ${(inst.indicators?.support_resistance?.resistance || []).join(', ') || 'N/A'}</div>
        <div class="status">Strategy: ${inst.strategy?.strategies?.[0]?.strategy || 'N/A'}</div>
        <div class="status">${inst.data_quality || 'N/A'}</div>
      `;
      grid.appendChild(card);
    }
  }

  const outlook = document.getElementById('outlook-content');
  if (outlook && data.ai_outlook) {
    populateAI(outlook, data.ai_outlook);
  }

  setLastUpdated(data.last_updated);
  showStale(data.data_quality);
}

async function loadHistory() {
  const grid = document.getElementById('history-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const files = ['nifty', 'banknifty', 'finnifty', 'midcpnifty', 'sensex'];
  for (const f of files) {
    const data = await fetchJSON(f);
    if (!data) continue;
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <h3>${f.toUpperCase()}</h3>
      <div class="status">Regime: ${data.regime?.regime || 'N/A'}</div>
      <div class="status">Confidence: ${data.regime?.confidence || 'N/A'}%</div>
      <div class="status">AI Outlook: ${data.ai_outlook?.market_summary || 'N/A'}</div>
      <div class="status">Strategy: ${data.strategy?.strategies?.[0]?.strategy || 'N/A'}</div>
      <div class="status">${data.data_quality || 'N/A'}</div>
      <div class="status">${new Date(data.last_updated).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })}</div>
    `;
    grid.appendChild(card);
  }
}

document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('market-grid')) loadDashboard();
  if (document.getElementById('history-grid')) loadHistory();
});