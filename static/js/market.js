async function loadMarket() {
  const data = await fetchJSON('market');
  if (!data) return;

  const grid = document.getElementById('market-grid');
  if (grid) {
    grid.innerHTML = '';
    for (const [symbol, inst] of Object.entries(data.instruments || {})) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <h3>${symbol}</h3>
        <div class="price">${formatPrice(inst.quote?.price)}</div>
        <div style="color:${inst.quote?.change >= 0 ? '#22c55e' : '#ef4444'}">${formatChange(inst.quote?.change)} (${formatChange(inst.quote?.change_pct)}%)</div>
        <span class="badge" style="background:${regimeColor(inst.regime?.regime)}20;color:${regimeColor(inst.regime?.regime)}">${inst.regime?.regime || 'N/A'}</span>
        <div class="status">VWAP: ${formatPrice(inst.indicators?.vwap)} | RSI: ${inst.indicators?.rsi?.toFixed(1) || 'N/A'}</div>
        <div class="status">Support: ${(inst.indicators?.support_resistance?.support || []).join(', ') || 'N/A'}</div>
        <div class="status">Resistance: ${(inst.indicators?.support_resistance?.resistance || []).join(', ') || 'N/A'}</div>
      `;
      grid.appendChild(card);
    }
  }

  const vix = await fetchJSON('vix');
  const vixEl = document.getElementById('vix-section');
  if (vixEl && vix) {
    vixEl.innerHTML = `<h3>India VIX</h3><div class="price">${formatPrice(vix.price)}</div><div>${formatChange(vix.change)} (${formatChange(vix.change_pct)}%)</div>`;
  }

  setLastUpdated(data.last_updated);
  showStale(data.data_quality);
}

document.addEventListener('DOMContentLoaded', loadMarket);