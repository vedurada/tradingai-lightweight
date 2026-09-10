async function loadScanner() {
  const grid = document.getElementById('scanner-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const symbols = ['nifty', 'banknifty', 'sensex', 'reliance', 'hdfcbank', 'icicibank', 'sbin', 'infy', 'tcs', 'lt', 'axisbank', 'adanient', 'bhartiartl'];
  for (const sym of symbols) {
    const data = await fetchJSON(sym);
    if (!data) continue;
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.regime = data.regime?.regime || '';
    card.dataset.confidence = data.regime?.confidence || 0;
    card.dataset.price = data.quote?.price || 0;
    card.dataset.support = (data.indicators?.support_resistance?.support || []).join(',');
    card.dataset.resistance = (data.indicators?.support_resistance?.resistance || []).join(',');
    card.dataset.dataQuality = data.data_quality || '';
    const ao = data.ai_outlook || {};
    card.dataset.evidence = ao.evidence_strength || 0;
    card.dataset.vol = ao.volatility_classification || '';
    card.dataset.structure = ao.market_structure || '';
    card.dataset.env = ao.strategy_environment || '';
    card.innerHTML = `
      <h3>${sym.toUpperCase()}</h3>
      <div class="price">${formatPrice(data.quote?.price)}</div>
      <div style="color:${data.quote?.change >= 0 ? '#22c55e' : '#ef4444'}">${formatChange(data.quote?.change)} (${formatChange(data.quote?.change_pct)}%)</div>
      <span class="badge" style="background:${regimeColor(data.regime?.regime)}20;color:${regimeColor(data.regime?.regime)}">${data.regime?.regime || 'N/A'}</span>
      <div class="status">Support: ${(data.indicators?.support_resistance?.support || []).join(', ') || 'N/A'}</div>
      <div class="status">Resistance: ${(data.indicators?.support_resistance?.resistance || []).join(', ') || 'N/A'}</div>
      <div class="status">Evidence: ${ao.evidence_strength || 'N/A'} | Vol: ${ao.volatility_classification || 'N/A'} | Structure: ${ao.market_structure || 'N/A'}</div>
      <div class="status">Env: ${ao.strategy_environment || 'N/A'} | Invalidation: ${ao.invalidation || 'N/A'}</div>
      <div class="status">${data.data_quality || 'N/A'}</div>
    `;
    grid.appendChild(card);
  }
}

function filterScanner(filter) {
  const cards = document.querySelectorAll('#scanner-grid .card');
  cards.forEach(card => {
    if (filter === 'all') { card.style.display = ''; return; }
    const regime = card.dataset.regime || '';
    const price = parseFloat(card.dataset.price) || 0;
    const support = (card.dataset.support || '').split(',').map(Number).filter(n => n);
    const resistance = (card.dataset.resistance || '').split(',').map(Number).filter(n => n);
    const confidence = parseInt(card.dataset.confidence) || 0;

    let show = false;
    if (filter === 'bullish' && regime.includes('BULLISH')) show = true;
    else if (filter === 'bearish' && regime.includes('BEARISH')) show = true;
    else if (filter === 'breakout' && regime.includes('BREAKOUT')) show = true;
    else if (filter === 'breakdown' && regime.includes('BREAKDOWN')) show = true;
    else if (filter === 'range' && regime.includes('RANGE')) show = true;
    else if (filter === 'high_vol' && confidence >= 70) show = true;
    else if (filter === 'near_support' && support.some(s => Math.abs(price - s) / price < 0.02)) show = true;
    else if (filter === 'near_resistance' && resistance.some(r => Math.abs(price - r) / price < 0.02)) show = true;

    card.style.display = show ? '' : 'none';
  });
}

document.addEventListener('DOMContentLoaded', () => { loadScanner(); startDataRefresh(loadScanner); });