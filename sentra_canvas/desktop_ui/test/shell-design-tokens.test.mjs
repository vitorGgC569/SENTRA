import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {dirname, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {DESIGN_TOKENS} from '../src/shell-design-tokens.js';

const root = dirname(fileURLToPath(import.meta.url));
const desktop = readFileSync(join(root, '../src/desktop.css'), 'utf8');
const polish = readFileSync(join(root, '../src/shell-polish.css'), 'utf8');
const integrate = readFileSync(join(root, '../src/shell-integrate.css'), 'utf8');
const styled = [desktop, polish, integrate].join('\n');

test('the shell declares every design token used by the new surfaces', () => {
  assert.ok(DESIGN_TOKENS.length > 0);
  const referenced = [...styled.matchAll(/var\((--sentra-[a-z0-9-]+)/g)].map(match => match[1]);
  assert.ok(referenced.includes('--sentra-sheet'));
  for (const token of new Set(referenced)) {
    assert.ok(DESIGN_TOKENS.includes(token), token);
    const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    assert.match(styled, new RegExp(`var\\(${escaped}\\s*,\\s*#[0-9a-fA-F]{3,8}\\)|${escaped}\\s*:`));
  }
  assert.match(desktop, /\.shell-failure \{[^}]*border:\s*1px solid var\(--shell-line\)/);
  assert.match(desktop, /\.shell-failure \{[^}]*background:\s*var\(--shell-panel\)/);
  assert.match(desktop, /\.shell-computer-status \{[^}]*display:\s*flex/);
  assert.match(desktop, /\.shell-update-menu \{[^}]*position:\s*relative/);
  assert.match(integrate, /\.opendots-shell \.shell-home-board \.shell-home-sheet \{/);
  assert.match(polish, /\.opendots-shell \.shell-dot-flow \{[^}]*min-height:\s*240px/);
});
