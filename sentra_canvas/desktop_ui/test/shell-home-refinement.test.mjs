import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {setChevron} from '../src/experience/cadencia/set-chevron.js';

const jsx = await readFile(new URL('../src/shell-home-board.jsx', import.meta.url), 'utf8');
const css = await readFile(new URL('../src/shell-integrate.css', import.meta.url), 'utf8');
const hosts = await Promise.all(['shell-app.jsx', 'shell-conversation.jsx', 'shell-dot-canvas.jsx', 'shell-dot-computer.jsx'].map(name =>
  readFile(new URL('../src/' + name, import.meta.url), 'utf8')));

test('the home refinement keeps search, space action, count, and chevron motion', () => {
  assert.match(jsx, /onClick=\{\(\) => onOpenSpace\(board\.focus\)\}>Abrir o Space</);
  assert.match(jsx, /status=\{row\.status\} execution=\{row\.execution\}/);
  assert.doesNotMatch(jsx, /executionValidated|mascotStatus|validated:\s*true/);
  for (const host of hosts) {
    const calls = host.match(/<DotMascot\b[^>]*>/g) || [];
    assert.ok(calls.length > 0);
    // The Home's Oxta is a fixed brand character, not an execution-status indicator.
    assert.equal(calls.every(call => /execution=\{[^}]+\}/.test(call) || /mascot="oxta" name="Oxta" size="hero" decorative/.test(call)), true);
    assert.equal(calls.some(call => /validated:\s*true|executionValidated|status="working"/.test(call)), false);
  }
  assert.match(jsx, /setChevron\(\{ open, reduced \}\)/);
  assert.match(jsx, /data-resend="false"/);
  assert.doesNotMatch(jsx, /translateY/);
  const search = css.slice(css.indexOf('.opendots-shell .shell-home-board .shell-home-search {'));
  assert.match(search, /width:\s*100%/);
  assert.match(search, /max-width:\s*none/);
  assert.match(search, /height:\s*40px/);
  assert.match(search, /border-radius:\s*999px/);
  const focusAt = jsx.indexOf('shell-home-focus');
  const failureAt = jsx.indexOf('<FailureSet');
  const searchAt = jsx.indexOf('id="shell-home-search"');
  const dotsAt = jsx.indexOf('Dots recentes');
  assert.ok(focusAt >= 0 && focusAt < failureAt && failureAt < searchAt && searchAt < dotsAt);
  assert.match(jsx, /shell-home-focus-line/);
  assert.match(jsx, /shell-home-conversation-dot/);
  assert.match(jsx, /shell-home-conversation-meta/);
  assert.match(css, /\.opendots-shell \.shell-home-focus \{[^}]*margin:\s*0;/s);
  assert.doesNotMatch(css, /margin:\s*0 0 8px/);
  assert.match(css, /\.opendots-shell \.shell-home-focus h1 \{[^}]*font-size:\s*40px/s);
  assert.match(css, /shell-home-focus-line \{[^}]*column-gap:\s*16px/s);
  assert.match(css, /shell-home-focus-line \{[^}]*justify-content:\s*flex-start/s);
  assert.doesNotMatch(css, /shell-home-open-space \{[^}]*justify-self:\s*end/s);
  assert.doesNotMatch(css, /@media \(min-width: 1440px\)/);
  assert.match(css, /@media \(max-width: 700px\) \{[^}]*font-size:\s*32px/s);
  const sum = css.slice(css.indexOf('.opendots-shell .shell-failure-sum {'));
  assert.match(sum, /height:\s*52px/);
  assert.match(sum, /#e2b15a/);
  assert.match(css, /\.opendots-shell \.shell-failure-consult \{[^}]*height:\s*32px/s);
  assert.match(css, /margin:\s*0 14px 8px/);
  const reduced = css.slice(css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(reduced, /\.cadence-set-chevron[^}]*transition:\s*none !important/s);
  assert.doesNotMatch(reduced.slice(reduced.indexOf('.cadence-set-chevron')), /cadence-set-chevron[^}]*transform:\s*none/s);
  assert.match(css, /\.opendots-shell \.shell-home-board \.shell-home-sheet \{[^}]*background:\s*var\(--sentra-sheet,\s*#17191e\)/s);
  assert.match(css, /\.opendots-shell \.shell-home-board \.shell-home-list \{[^}]*gap:\s*0/s);
  assert.match(css, /shell-home-sheet button:focus-visible \{[^}]*outline-offset:\s*-4px/s);
  assert.match(css, /shell-home-search input:focus-visible \{[^}]*#ffffff/s);
  assert.match(css, /shell-home-open-space:focus-visible \{[^}]*#ffffff/s);
  assert.match(css, /shell-home-board h2 \{[^}]*margin:\s*0/s);
  const opened = setChevron({ open: true, reduced: false });
  const still = setChevron({ open: true, reduced: true });
  assert.equal(opened.size, 16);
  assert.equal(opened.transition, 'transform 200ms cubic-bezier(0.22, 1, 0.36, 1)');
  assert.equal(still.transition, 'none');
  assert.equal(still.transform, 'rotate(90deg)');
  assert.equal(still.transform.includes('translate'), false);
});

test('at 390 the dot line stacks name and phrase and keeps Ativo outside that column', () => {
  const mobileAt = css.indexOf('@media (max-width: 700px)');
  const wide = css.slice(0, mobileAt);
  const narrow = css.slice(mobileAt, css.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(wide, /grid-template-columns:\s*28px minmax\(0, 1fr\) minmax\(0, 1fr\) auto 16px/);
  assert.doesNotMatch(wide, /grid-template-columns:\s*28px minmax\(0, 1fr\) auto 16px/);
  assert.match(narrow, /grid-template-columns:\s*28px minmax\(0, 1fr\) auto 16px/);
  assert.match(narrow, /max-height:\s*56px/);
  assert.match(narrow, /shell-home-list > button strong \{[^}]*grid-column:\s*2;[^}]*grid-row:\s*1;[^}]*text-overflow:\s*ellipsis/s);
  assert.match(narrow, /shell-home-dot-context \{[^}]*grid-column:\s*2;[^}]*grid-row:\s*2;[^}]*text-overflow:\s*ellipsis/s);
  assert.match(narrow, /small\[data-phase\] \{[^}]*white-space:\s*nowrap;[^}]*min-width:\s*max-content/s);
  assert.match(narrow, /shell-home-list > button > svg \{[^}]*min-width:\s*16px/s);
  assert.match(css, /shell-home-conversation-sum \{[^}]*max-height:\s*56px/s);
  assert.match(css, /grid-template-columns:\s*minmax\(0, 1fr\) 16px/);
  assert.match(css, /shell-home-conversation-dot \{[^}]*flex:\s*0 0 auto/s);
  assert.doesNotMatch(css, /shell-home-conversation-sum span,\s*\.opendots-shell \.shell-home-conversation-sum small \{[^}]*min-width:\s*max-content/s);
  assert.doesNotMatch(jsx, /Trabalhando|ocupado/);
  assert.match(jsx, /\{row\.fact\}/);
  assert.match(jsx, /\{row\.context\}/);
});
