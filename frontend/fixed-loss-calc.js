/* E.2 fixed-loss economics calculator — client presentation layer.
 *
 * ISOLATION CONTRACT: this file performs NO pricing, payoff, cost, lot,
 * breakeven, reward/risk or spread arithmetic. It collects input, builds a
 * query string for GET /api/economics/calculate, and renders the response
 * values verbatim. The single arithmetic used here is scaling returned
 * coordinates onto the SVG chart, which is layout, not economics.
 */
'use strict';

var API = '/api/economics/calculate';

/* Option-type layout per strategy. Side (buy/sell) is never entered here:
   the authoritative server module infers it from strike order. */
var STRATEGIES = {
  BULL_PUT_SPREAD:  { label: 'Bull Put Spread',  types: ['PE', 'PE'] },
  BULL_CALL_SPREAD: { label: 'Bull Call Spread', types: ['CE', 'CE'] },
  BEAR_CALL_SPREAD: { label: 'Bear Call Spread', types: ['CE', 'CE'] },
  BEAR_PUT_SPREAD:  { label: 'Bear Put Spread',  types: ['PE', 'PE'] },
  IRON_CONDOR:     { label: 'Iron Condor',      types: ['PE', 'PE', 'CE', 'CE'] }
};

function $(id) { return document.getElementById(id); }

function esc(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

/* Number formatting for display only. */
function rs(v) {
  if (v == null || isNaN(v)) { return '—'; }
  return '₹' + Number(v).toLocaleString('en-IN', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });
}
function pts(v) {
  if (v == null || isNaN(v)) { return '—'; }
  return Number(v).toLocaleString('en-IN', {
    minimumFractionDigits: 2, maximumFractionDigits: 2
  });
}

function buildLegRows() {
  var key = $('strategy').value;
  var types = STRATEGIES[key].types;
  var host = $('legs');
  var html = '<table class="flc-legs"><thead><tr>'
    + '<th>Leg</th><th>Option</th><th>Strike</th><th>Premium</th></tr></thead><tbody>';
  for (var i = 0; i < types.length; i++) {
    html += '<tr>'
      + '<td>' + (i + 1) + '</td>'
      + '<td><select id="leg' + i + '_type" aria-label="Leg ' + (i + 1) + ' option type">'
      + '<option value="PE"' + (types[i] === 'PE' ? ' selected' : '') + '>Put (PE)</option>'
      + '<option value="CE"' + (types[i] === 'CE' ? ' selected' : '') + '>Call (CE)</option>'
      + '</select></td>'
      + '<td><input id="leg' + i + '_strike" type="number" step="any" min="0.01" inputmode="decimal" placeholder="e.g. 26000"></td>'
      + '<td><input id="leg' + i + '_premium" type="number" step="any" min="0.01" inputmode="decimal" placeholder="e.g. 120"></td>'
      + '</tr>';
  }
  html += '</tbody></table>';
  host.innerHTML = html;
}

function setMsg(cls, html) {
  var m = $('msg');
  m.className = 'flc-msg ' + cls;
  m.innerHTML = html;
  m.hidden = false;
}
function clearMsg() { $('msg').hidden = true; $('msg').innerHTML = ''; }

/* Validation is limited to "is this field filled / is it a positive number".
   No economic rule is evaluated here. */
function collect() {
  var key = $('strategy').value;
  var types = STRATEGIES[key].types;
  var p = new URLSearchParams();
  p.set('instrument', $('instrument').value);
  p.set('strategy', key);
  p.set('expiry', $('expiry').value.trim());

  var expiry = $('expiry').value.trim();
  if (!expiry) { return { error: 'Enter an expiry label, for example 30JAN2026.' }; }

  var lotsRaw = $('lots').value.trim();
  if (!lotsRaw) { return { error: 'Enter how many lots you want to study.' }; }
  if (!(Number(lotsRaw) >= 1)) { return { error: 'Lots must be 1 or more.' }; }
  p.set('lots', lotsRaw);

  /* Lot size stays blank by default so the server applies its own
     authoritative value. Only send it when the visitor overrides it. */
  var lotRaw = $('lot_size').value.trim();
  if (lotRaw) { p.set('lot_size', lotRaw); }

  for (var i = 0; i < types.length; i++) {
    var k = $('leg' + i + '_strike').value.trim();
    var pr = $('leg' + i + '_premium').value.trim();
    if (!k || !pr) { return { error: 'Enter a strike and a premium for every leg.' }; }
    if (!(Number(k) > 0) || !(Number(pr) > 0)) {
      return { error: 'Strike and premium must both be greater than zero.' };
    }
    p.set('leg' + i + '_type', $('leg' + i + '_type').value);
    p.set('leg' + i + '_strike', k);
    p.set('leg' + i + '_premium', pr);
  }
  return { params: p };
}

function kpi(label, value, warn) {
  return '<div class="flc-kpi' + (warn ? ' warn' : '') + '">'
    + '<div class="k">' + esc(label) + '</div><div class="v">' + esc(value) + '</div></div>';
}

function renderLegs(d) {
  var rows = '';
  for (var i = 0; i < d.legs.length; i++) {
    rows += '<tr><td>' + (i + 1) + '</td>'
      + '<td>' + esc(d.legs[i].option_type) + '</td>'
      + '<td>' + esc(pts(d.legs[i].strike)) + '</td>'
      + '<td>' + esc(pts(d.legs[i].premium != null ? d.legs[i].premium : d.legs[i].bid)) + '</td>'
      + '<td>' + esc(d.leg_sides[i]) + '</td></tr>';
  }
  return '<table class="flc-legs"><thead><tr><th>Leg</th><th>Option</th><th>Strike</th>'
    + '<th>Premium</th><th>Side</th></tr></thead><tbody>' + rows + '</tbody></table>';
}

/* Pure plotting: maps API-returned spots / totals onto SVG coordinates. */
function renderChart(curve) {
  var W = 640, H = 260, PADL = 62, PADR = 14, PADT = 12, PADB = 30;
  var xs = curve.spots, ys = curve.pnl_total_rs;
  var x0 = xs[0], x1 = xs[xs.length - 1];
  var lo = Math.min.apply(null, ys), hi = Math.max.apply(null, ys);
  if (lo === hi) { lo -= 1; hi += 1; }
  var sx = function (v) { return PADL + (v - x0) / (x1 - x0 || 1) * (W - PADL - PADR); };
  var sy = function (v) { return H - PADB - (v - lo) / (hi - lo) * (H - PADT - PADB); };

  var ptsAttr = [], i;
  for (i = 0; i < xs.length; i++) {
    ptsAttr.push(sx(xs[i]).toFixed(1) + ',' + sy(ys[i]).toFixed(1));
  }

  var g = '';
  for (i = 0; i <= 4; i++) {
    var val = lo + (hi - lo) * i / 4;
    var y = sy(val).toFixed(1);
    g += '<line class="flc-gridline" x1="' + PADL + '" y1="' + y + '" x2="' + (W - PADR) + '" y2="' + y + '"></line>'
      + '<text class="flc-axis" x="' + (PADL - 6) + '" y="' + y + '" text-anchor="end" dominant-baseline="middle">'
      + esc(Math.round(val)) + '</text>';
  }

  var zeroY = sy(0).toFixed(1);
  var xlab = '';
  for (i = 0; i < xs.length; i += Math.max(1, Math.floor(xs.length / 6))) {
    xlab += '<text class="flc-axis" x="' + sx(xs[i]).toFixed(1) + '" y="' + (H - 10) + '" text-anchor="middle">'
      + esc(Math.round(xs[i])) + '</text>';
  }

  return '<svg class="flc-chart" viewBox="0 0 ' + W + ' ' + H + '" role="img" '
    + 'aria-label="Profit and loss at expiry across the plotted index range">'
    + g
    + '<line class="flc-zero" x1="' + PADL + '" y1="' + zeroY + '" x2="' + (W - PADR) + '" y2="' + zeroY + '"></line>'
    + '<polyline fill="none" stroke="#1d4ed8" stroke-width="2" points="' + ptsAttr.join(' ') + '"></polyline>'
    + xlab
    + '<text class="flc-axis" x="' + PADL + '" y="' + (PADT + 4) + '">Total P&amp;L (₹)</text>'
    + '<text class="flc-axis" x="' + (W - PADR) + '" y="' + (H - 10) + '" text-anchor="end">Index level at expiry</text>'
    + '</svg>';
}

function render(d) {
  var e = d.economics;
  var html = '';

  html += '<div class="flc-kpis">';
  html += kpi('Net credit / debit', (d.net_basis === 'NET_CREDIT' ? '+' : '−') + rs(e.net_credit != null ? e.net_credit : e.net_debit));
  html += kpi('Maximum reward', rs(e.max_reward_rs));
  html += kpi('Maximum risk', rs(e.max_risk_rs), true);
  if (e.breakeven != null) {
    html += kpi('Breakeven', pts(e.breakeven));
  } else if (e.breakeven_lower != null) {
    html += kpi('Lower breakeven', pts(e.breakeven_lower));
    html += kpi('Upper breakeven', pts(e.breakeven_upper));
  }
  html += kpi('Reward : risk', e.reward_risk != null ? e.reward_risk + ' : 1' : '—');
  html += kpi('Estimated costs', rs(d.estimated_costs_rs));
  html += '</div>';

  html += '<h2>Legs as priced by the server</h2>' + renderLegs(d);
  html += '<p class="flc-hint">Sides are assigned by the authoritative calculation module, not by this page. '
    + 'Lot size ' + esc(d.lot_size) + ' × ' + esc(d.lots) + ' lot' + (d.lots === 1 ? '' : 's') + '.</p>';

  html += '<h2>Profit and loss at expiry</h2>' + renderChart(d.curve);
  html += '<p class="flc-hint">Charted over ' + esc(pts(d.range.low)) + ' to ' + esc(pts(d.range.high))
    + ' across ' + esc(d.range.points) + ' points.</p>';

  if (d.curve_reconciled === false) {
    html += '<div class="flc-msg err">The selected range does not reach both structural extremes, '
      + 'so the chart could not be cross-checked against the summary figures. '
      + 'Widen the range or use the default to see the full curve.</div>';
  }

  html += '<div class="flc-note">' + esc(d.data_gate_note) + '</div>';
  $('out').innerHTML = html;
  $('out').hidden = false;
}

function run() {
  clearMsg();
  var c = collect();
  if (c.error) { setMsg('err', esc(c.error)); return; }

  $('calc').disabled = true;
  setMsg('busy', 'Calculating…');

  fetch(API + '?' + c.params.toString(), { method: 'GET', headers: { 'Accept': 'application/json' } })
    .then(function (r) { return r.json().then(function (j) { return { status: r.status, body: j }; }); })
    .then(function (res) {
      $('calc').disabled = false;
      var j = res.body || {};
      if (res.status === 200 && j.state === 'CALCULATED') {
        render(j.data);
        clearMsg();
        return;
      }
      $('out').hidden = true;
      var reasons = (j.data && j.data.reasons) || [];
      var html = '<b>' + esc(j.state || 'UNAVAILABLE') + '</b>';
      if (reasons.length) {
        html += '<ul>' + reasons.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>';
      }
      setMsg('err', html);
    })
    .catch(function () {
      $('calc').disabled = false;
      $('out').hidden = true;
      setMsg('err', 'Could not reach the calculation service. Try again in a moment.');
    });
}

document.addEventListener('DOMContentLoaded', function () {
  $('strategy').addEventListener('change', buildLegRows);
  $('calc').addEventListener('click', run);
  buildLegRows();
});