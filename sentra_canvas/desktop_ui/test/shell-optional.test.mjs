import {test} from 'node:test';
import assert from 'node:assert/strict';
import {presentOptional} from '../src/shell-optional.js';

test('a missing optional document does not invent a catalog', () => {
  const view = presentOptional(null);
  assert.equal(view.available, false);
  assert.equal(view.homologated, false);
  assert.equal(view.closed_by_absence, false);
  assert.equal(view.downloads, false);
  assert.deepEqual(view.items, []);
});

test('absence stays open and a true homologated flag is forced false', () => {
  const view = presentOptional({items: [
    {surface: 'marketplace', present: false, available: true, homologated: true, closed_by_absence: true, reason: 'CATALOG_ABSENT', needs: 'catalogo local'},
    {surface: 'other', present: true},
  ]});
  assert.equal(view.items.length, 1);
  assert.equal(view.items[0].surface, 'marketplace');
  assert.equal(view.items[0].homologated, false);
  assert.equal(view.items[0].closed_by_absence, false);
  assert.equal(view.items[0].capability_closed, false);
  assert.equal(view.items[0].grants_created, false);
  assert.equal(view.items[0].opt_in_required, true);
});
