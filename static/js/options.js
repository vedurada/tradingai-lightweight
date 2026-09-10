async function loadOptions() {
  const grid = document.getElementById('options-grid');
  if (!grid) return;
  grid.innerHTML = '';

  const files = ['nifty', 'banknifty'];
  for (const f of files) {
    const data = await fetchJSON(f);
    if (!data) continue;
    const card = document.createElement('div');
    card.className = 'card';
    card.innerHTML = `
      <h3>${f.toUpperCase()}</h3>
      <div class="price">${formatPrice(data.quote?.price)}</div>
      <span class="badge" style="background:${regimeColor(data.regime?.regime)}20;color:${regimeColor(data.regime?.regime)}">${data.regime?.regime || 'N/A'}</span>
      <div class="status">PCR: ${data.options?.pcr?.toFixed(3) || 'N/A'}</div>
      <div class="status">Max Pain: ${formatPrice(data.options?.max_pain?.max_pain)}</div>
      <div class="status">IV Avg: ${data.options?.iv_stats?.avg_iv || 'N/A'}</div>
      <div class="status">Strategy: ${data.strategy?.strategies?.[0]?.strategy || 'N/A'}</div>
      <div class="status">${data.data_quality || 'N/A'}</div>
    `;
    grid.appendChild(card);
  }
}

function filterOptions(filter) {
  const cards = document.querySelectorAll('#options-grid .card');
  cards.forEach(card => {
    if (filter === 'all') { card.style.display = ''; return; }
    const regime = card.querySelector('.badge')?.textContent || '';
    const strategy = card.textContent || '';
    if (filter === 'bullish' && regime.includes('BULLISH')) card.style.display = '';
    else if (filter === 'bearish' && regime.includes('BEARISH')) card.style.display = '';
    else if (filter === 'neutral' && regime.includes('RANGE')) card.style.display = '';
    else if (filter === 'high_iv' && strategy.includes('High IV')) card.style.display = '';
    else if (filter === 'defined_risk' && strategy.includes('Defined')) card.style.display = '';
    else card.style.display = 'none';
  });
}

document.addEventListener('DOMContentLoaded', loadOptions);