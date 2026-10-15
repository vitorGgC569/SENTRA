import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resumableWorkSurface } from '../src/shell-navigation.js';

const home = { project_id: 'p', spaces: [{ project_id: 'p', space_id: 's' }], dots: [{ project_id: 'p', space_id: 's', dot_id: 'd' }],
  conversations: [{ project_id: 'p', space_id: 's', dot_id: 'd', conversation_id: 'c' }] };
test('resume uses canonical conversation identity instead of a stored Dot preference', () => {
  const result = resumableWorkSurface({ view: 'chat', project_id: 'p', space_id: 's', conversation_id: 'c', dot_id: 'stale' }, home);
  assert.equal(result.dot_id, 'd');
  assert.equal(result.conversation_id, 'c');
});
test('deleted and foreign work is not advertised as resumable', () => {
  const surface = { view: 'chat', project_id: 'p', space_id: 's', conversation_id: 'c', dot_id: 'd' };
  for (const value of [{ ...surface, project_id: 'foreign' }, { ...surface, space_id: 'foreign' }, { ...surface, conversation_id: 'deleted' },
    { ...surface, view: 'canvas', dot_id: 'deleted' }, { ...surface, view: 'documents', space_id: null }, { ...surface, view: 'home' }]) assert.equal(resumableWorkSurface(value, home), null);
  assert.equal(resumableWorkSurface(surface, { ...home, project_id: undefined }), null);
});
