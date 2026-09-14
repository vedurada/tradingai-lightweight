# Ad Placement Policy (Track B)

Only Google AdSense **auto ads** are used — no manually placed ad units.
This policy keeps ads away from interactive and financial-decision content.

## Forbidden zones

- Within ~150px of trade Call-To-Action elements: `.cta-row a`, `button`,
  chat send controls (`#tai-chat` widget), strategy "Open →" links.
- Inside any `<form>` element.
- Sticky/fixed bottom ad formats on screens that already have a fixed CTA bar.
- Between a price/level figure and its immediately adjacent action button
  (prevents mis-taps being read as ad clicks).

## Technical guard

`static/css/main.css` carries a separation rule pushing `ins.adsbygoogle`
away from `.cta-row` and `button` elements. If auto-ads ever inject into a
forbidden zone, add a page-level exclusion rather than moving financial content.

## Review

Re-check placements quarterly or after any page-layout change. Accidental-click
clusters (AdSense Policy Center) trigger an immediate layout audit.
