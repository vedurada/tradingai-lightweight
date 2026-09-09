async function loadScanner() {
  const grid = document.getElementById('scanner-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const config = await fetchJSON('../config/instruments');
  if (!config) return;

  for (const inst of config.indices.concat(config.stocks)) {
    const data = await fetchJSON(inst.symbol.toLowerCase());
    if (!data) continue;
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <h3>${inst.symbol}</h3>
      <div class="price">${formatPrice(data.quote?.price)}</div>
      <div style="color:${data.quote?.change >= 0 ? '#22c55e' : '#ef4444'}">${formatChange(data.quote?.change)} (${formatChange(data.quote?.change_pct)}%)</div>
      <span class="badge" style="background:${regimeColor(data.regime?.regime)}20;color:${regimeColor(data.regime?.regime)}">${data.regime?.regime || 'N/A'}</span>
      <div class="status">Support: ${(data.indicators?.support_resistance?.support || []).join(', ') || 'N/A'}</div>
      <div class="status">Resistance: ${(data.indicators?.support_resistance?.resistance || []).join(', ') || 'N/A'}</div>
      <div class="status">${data.data_quality || 'N/A'}</div>
    `;
    grid.appendChild(card);
  }
}

function filterScanner(filter) {
  const cards = document.querySelectorAll('#scanner-grid .card');
  cards.forEach(card => {
    if (filter === 'all') { card.style.display = ''; return; }
    const regime = card.querySelector('.badge')?.textContent || '';
    const price = card.querySelector('.price')?.textContent || '';
    if (filter === 'bullish' && regime.includes('BULLISH')) card.style.display = '';
    else if (filter === 'bearish' && regime.includes('BEARISH')) card.style.display = '';
    else if (filter === 'breakout' && regime.includes('BREAKOUT')) card.style.display = '';
    else if (filter === 'breakdown' && regime.includes('BREAKDOWN')) card.style.display = '';
    else if (filter === 'range' && regime.includes('RANGE')) card.style.display = '';
    else if (filter === 'high_vol' && regime.includes('HIGH_VOLATILITY')) card.style.display = '';
    else if (filter === 'near_support' && price) card.style.display = '';
    else if (filter === 'near_resistance' && price) card.style.display = '';
    else card.style.display = 'none';
  });
}

document.addEventListener('DOMContentLoaded', loadScanner);