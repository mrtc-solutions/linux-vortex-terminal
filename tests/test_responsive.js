'use strict';

// Structural viewport regression checks. These do not pretend to replace a
// browser screenshot; they pin the narrow-layout rules that prevent the known
// text/icon collisions at 800, 600, and 380 CSS px (including zoom-reduced
// viewports).
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const root = path.join(__dirname, '..');
const css = fs.readFileSync(path.join(root, 'frontend', 'styles.css'), 'utf8');
const html = fs.readFileSync(path.join(root, 'frontend', 'index.html'), 'utf8');

function media(maxWidth) {
  const marker = `@media (max-width: ${maxWidth}px)`;
  const start = css.indexOf(marker);
  assert.notStrictEqual(start, -1, `responsive breakpoint ${maxWidth}px exists`);
  const open = css.indexOf('{', start);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return css.slice(open + 1, i);
    }
  }
  throw new Error(`unterminated ${maxWidth}px media block`);
}

const at800 = media(800);
const at600 = media(600);
const at380 = media(380);
assert.match(at800, /\.nav-item\s*\{[^}]*font-size:\s*0[^}]*overflow:\s*hidden/s, 'collapsed rail hides bare text labels instead of overlapping content');
assert.match(at800, /\.nav-icon\s*\{[^}]*width:\s*100%[^}]*font-size:\s*18px/s, 'collapsed navigation icons retain an explicit readable size');
assert.match(at800, /\.grid-row[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s, 'main grids permit content to shrink without overflow');
assert.match(at800, /\.model-actions[^}]*flex-direction:\s*column/s, 'model input, role, and action reflow vertically');
assert.match(at600, /\.quick-actions\s*\{[^}]*minmax\(0,\s*1fr\)/s, 'quick actions become one shrinkable column');
assert.match(at600, /\.setting-card\s*\{[^}]*grid-template-columns:\s*auto\s+minmax\(0,\s*1fr\)/s, 'setting controls move onto a collision-free narrow grid');
assert.match(at600, /\.dep-row\s*\{[^}]*minmax\(0,\s*1fr\)\s+auto/s, 'dependency rows reflow text above controls');
assert.match(at600, /\.terminal-panes\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s*!important/s, 'split terminals stack on narrow viewports');
assert.match(at600, /\.surface-window\s*\{[^}]*padding:\s*8px/s, 'modal usable width is preserved on phones');
assert.match(at380, /\.sidebar\s*\{[^}]*width:\s*52px[^}]*flex-basis:\s*52px/s, 'very narrow rail has a bounded matching width and basis');

const ids = [...html.matchAll(/\bid="([^"]+)"/g)].map(match => match[1]);
assert.strictEqual(new Set(ids).size, ids.length, 'static document IDs are unique');
assert.match(html, /<meta\s+name="viewport"\s+content="width=device-width,\s*initial-scale=1"/i, 'mobile viewport uses CSS pixels');
const navButtons = [...html.matchAll(/<button class="nav-item[^"]*"[^>]*>([\s\S]*?)<\/button>/g)];
assert.ok(navButtons.length >= 10, 'primary and secondary navigation are present');
for (const [, body] of navButtons) {
  assert.match(body, /class="nav-icon"/, 'every collapsed navigation item retains an icon');
  assert.ok(body.replace(/<[^>]+>/g, '').trim(), 'every icon-only visual button retains an accessible text name');
}
assert.ok(html.includes('id="model-role-input"'), 'custom model downloads expose post-verification role activation');

console.log('responsive collision invariants: PASS');
