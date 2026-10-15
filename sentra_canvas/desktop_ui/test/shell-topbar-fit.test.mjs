import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const css = await readFile(new URL('../src/shell-integrate.css', import.meta.url), 'utf8');

test('the breadcrumb yields and the run label keeps its full line', () => {
  const breadcrumb = css.slice(css.indexOf('.opendots-shell .shell-breadcrumb {'), css.indexOf('.opendots-shell .shell-breadcrumb > span'));
  assert.match(breadcrumb, /overflow:\s*hidden/);
  assert.match(breadcrumb, /min-width:\s*min-content/);
  assert.match(css, /\.opendots-shell \.shell-breadcrumb > strong \{[^}]*flex:\s*0 0 auto/s);
  const narrow = css.slice(css.indexOf('@container shell (max-width: 560px)'));
  assert.match(narrow, /\.shell-breadcrumb > span,\s*\.opendots-shell \.shell-breadcrumb > svg \{ display: none; \}/);
  const label = css.slice(css.lastIndexOf('.opendots-shell .shell-topbar .shell-run-label {'));
  assert.match(label, /flex:\s*0 0 auto/);
  assert.match(label, /white-space:\s*nowrap/);
  assert.match(label, /margin-inline-start:\s*8px/);
  assert.match(css, /\.opendots-shell \.shell-topbar \{[^}]*overflow:\s*visible/s);
  assert.match(css, /\.opendots-shell \.shell-update-panel \{[^}]*position:\s*absolute/s);
  assert.doesNotMatch(css, /shell-run-label\s*\{[^}]*display:\s*none/s);
});
