import test from 'node:test';
import assert from 'node:assert/strict';
import { deliveryView, loopRequest, goalCost } from '../../sentra_canvas/desktop_ui/src/durable-web-state.js';
test('uncertain deliveries retain request identity and never project success', () => {
  const value = deliveryView({ request_id: 'real-request', state: 'UNCONFIRMED', model_state: 'ADVERTISED' });
  assert.equal(value.requires_reconciliation, true);
  assert.equal(value.request_id, 'real-request');
  assert.equal(value.model_state, 'ADVERTISED');
  assert.equal(deliveryView({ state: 'HTTP_200', model_state: 'Plus' }).state, 'UNKNOWN');
  assert.equal(deliveryView({ state: 'HTTP_200', model_state: 'Plus' }).model_state, 'UNKNOWN');
});
test('Loop requires finite limits and uses central goal identity without consent booleans', () => {
  assert.throws(() => loopRequest('ws', { goal_id: 'goal' }, { steps: '4', cost: '', seconds: '600' }));
  assert.throws(() => loopRequest('ws', { goal_id: 'goal' }, { steps: '17', cost: '1', seconds: '600' }));
  assert.deepEqual(loopRequest('ws', { goal_id: 'goal' }, { steps: '4', cost: '0', seconds: '600' }),
    { ws: 'ws', action: 'start', goal_id: 'goal', max_steps: 4, max_cost_usd: 0, deadline_seconds: 600 });
  assert.equal(goalCost({ cost_usd: null }), 'Indisponível');
  assert.equal(goalCost({ cost_usd: 0 }), '$0.0000');
});
