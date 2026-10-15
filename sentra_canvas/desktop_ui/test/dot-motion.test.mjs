import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { mascotMotionState, paintCopy, presentDot } from '../src/dot-motion.js';

const copies = ['blue.svg', 'mint.svg', 'orange.svg', 'purple.svg'];
const here = typeof import.meta.dirname === 'string'
  ? import.meta.dirname
  : path.dirname(fileURLToPath(import.meta.url));
const directory = path.join(here, '../src/assets/dot-motion');
const pngDirectory = path.join(here, '../src/assets/opendots');
const pngHashes = {
  'blue.png': 'bf8ef19c7b7d753c11ba05e411f15a0733bcb810541bc88fb34c38427c6a6040',
  'mint.png': 'aebbd4a27e346b7a2f41976bcdae4b144e42219cce77182053cfe4140bb6486f',
  'orange.png': 'bf9a2f9f6859c2931b9a4062117deb7d06fba77b190b5ad52a90587f368b34a7',
  'purple.png': '9fb3e53fc90b4fe881e1c1f8121dd32fbe9882dbc989156c40b0a8fadc348441',
};

function originalCore(markup) {
  const match = markup.match(/<g\b[^>]*\bid="dot-original"[^>]*>([\s\S]*?)<\/g>/);
  assert.ok(match, 'dot-original core');
  return match[1];
}

test('each Dot copy moves on interaction and keeps its original markup', () => {
  assert.equal(copies.length, 4);
  const cores = new Map();
  for (const name of copies) {
    const file = path.join(directory, name);
    const original = fs.readFileSync(file, 'utf8');
    const idle = presentDot(original, { time: 0, interaction: 'idle' });
    const pressed = presentDot(original, { time: 0.5, interaction: 'press' });
    const hovered = presentDot(original, { time: 1, interaction: 'hover' });
    assert.equal(idle.markup, original);
    assert.equal(pressed.markup, original);
    assert.equal(hovered.markup, original);
    assert.equal(fs.readFileSync(file, 'utf8'), original);
    assert.notEqual(pressed.presentation.strokeDashoffset, idle.presentation.strokeDashoffset);
    assert.notEqual(hovered.presentation.opacity, idle.presentation.opacity);
    assert.match(original, /id="dot-original"/);
    const core = originalCore(original);
    assert.notEqual(core.trim(), '');
    cores.set(name, core);
    const pngName = name.replace(/\.svg$/, '.png');
    const png = fs.readFileSync(path.join(pngDirectory, pngName));
    assert.equal(crypto.createHash('sha256').update(png).digest('hex'), pngHashes[pngName]);
  }
  for (const [name, core] of cores) {
    for (const [other, otherCore] of cores) {
      if (name !== other) assert.notEqual(core, otherCore);
    }
  }
});

test('lifecycle active is not working until the host validates execution', () => {
  assert.notEqual(mascotMotionState('active'), 'working');
  assert.equal(mascotMotionState('active'), 'idle');
  assert.notEqual(mascotMotionState('running'), 'working');
  assert.notEqual(mascotMotionState('working'), 'working');
  assert.notEqual(mascotMotionState('active', { validated: true, status: 'running' }), 'working');
  assert.notEqual(mascotMotionState('working', { validated: false, workItemState: 'RUNNING' }), 'working');
  const validated = { validated: true, workItemState: 'RUNNING', operationState: 'RUNNING' };
  assert.equal(mascotMotionState('active', validated), 'working');
  assert.equal(mascotMotionState('running', { validated: true, operationState: 'RUNNING' }), 'working');
  assert.equal(mascotMotionState('needs_input'), 'needs-input');
  assert.equal(mascotMotionState('paused', validated), 'working');
  assert.equal(mascotMotionState('completed'), 'complete');
});

test('paintCopy leaves opacity and stroke-dashoffset on dot-original unchanged', () => {
  const source = [
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128">',
    '<g id="dot-original" opacity="1" stroke-dashoffset="0">',
    '<ellipse cx="64" cy="80" rx="20" ry="16" fill="#3c92ee"/>',
    '</g>',
    '<g id="dot-motion" fill="none" stroke="#1d4e86" stroke-width="2" stroke-dasharray="4 6" stroke-dashoffset="0" opacity="1" transform="translate(0 0)">',
    '<ellipse cx="64" cy="80" rx="28" ry="24"/>',
    '</g>',
    '</svg>',
  ].join('');
  const presentation = presentDot(source, { time: 1, interaction: 'hover' }).presentation;
  const painted = paintCopy(source, presentation);
  const tag = (markup, id) => {
    const match = markup.match(new RegExp(`<g\\b[^>]*\\bid="${id}"[^>]*>`));
    assert.ok(match, id);
    return match[0];
  };
  const originalBefore = tag(source, 'dot-original');
  const motionBefore = tag(source, 'dot-motion');
  const originalAfter = tag(painted, 'dot-original');
  const motionAfter = tag(painted, 'dot-motion');
  assert.match(originalBefore, /opacity="1"/);
  assert.match(originalBefore, /stroke-dashoffset="0"/);
  assert.equal(originalAfter, originalBefore);
  assert.match(originalAfter, /opacity="1"/);
  assert.match(originalAfter, /stroke-dashoffset="0"/);
  assert.notEqual(motionAfter, motionBefore);
  assert.ok(motionAfter.includes(`opacity="${presentation.opacity}"`));
  assert.ok(motionAfter.includes(`stroke-dashoffset="${presentation.strokeDashoffset}"`));
  assert.equal(painted.replace(motionAfter, motionBefore), source);
});
