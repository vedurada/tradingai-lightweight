async function loadStrategies() {
  const grid = document.getElementById('strategy-grid');
  if (!grid) return;
  grid.innerHTML = '<div class="card">Loading strategies...</div>';

  const symbols = ['nifty', 'banknifty', 'sensex'];
  let html = '';

  for (const sym of symbols) {
    const data = await fetchJSON(sym);
    if (!data) continue;
    const strategy = data.strategy || {};
    const regime = data.regime || {};
    const scenarios = data.scenarios || [];

    html += `
      <div class="card">
        <h3>${sym.toUpperCase()}</h3>
        <div class="status">Regime: ${regime.regime || 'N/A'}</div>
        <div class="status">Confidence: ${regime.confidence || 'N/A'}%</div>
        <div class="status">Strategy: ${strategy.strategies?.[0]?.strategy || 'N/A'}</div>
        <div class="status">Market: ${strategy.strategies?.[0]?.market_condition || 'N/A'}</div>
        <div class="status">Expiry: ${strategy.strategies?.[0]?.expiry || 'N/A'}</div>
        <div class="status">Entry: ${strategy.strategies?.[0]?.entry_trigger || 'N/A'}</div>
        <div class="status">Stop Loss: ${strategy.strategies?.[0]?.stop_loss || 'N/A'}</div>
        <div class="status">Target: ${strategy.strategies?.[0]?.target || 'N/A'}</div>
        ${scenarios.length ? '<h4>Scenarios</h4>' : ''}
        ${scenarios.map(s => `
          <div class="status">${s.scenario_type || 'N/A'}: ${s.description || 'N/A'}</div>
          <div class="status">Trigger: ${s.trigger || 'N/A'} | Target: ${s.target || 'N/A'} | Stop: ${s.stop_loss || 'N/A'}</div>
        `).join('')}
      </div>`;
  }

  if (!html) {
    html = '<div class="card">No strategy data available</div>';
  }
  grid.innerHTML = html;
  setLastUpdated(new Date().toISOString());
}

document.addEventListener('DOMContentLoaded', () => { loadStrategies(); startDataRefresh(loadStrategies); });