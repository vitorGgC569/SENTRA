import {test} from 'node:test';
import assert from 'node:assert/strict';
import {networkPayload, presentNetwork, presentNetworkResult} from '../src/shell-network.js';

test('an absent document stays closed and does not invent peers', () => {
  const view = presentNetwork(null);
  assert.equal(view.renderer, 'lumen');
  assert.equal(view.available, false);
  assert.equal(view.physical_proof, false);
  assert.equal(view.enabled, false);
  assert.equal(view.listening, false);
  assert.equal(view.disconnected, true);
  assert.deepEqual(view.peers, []);
});

test('a read shows configuration and peers and drops identity', () => {
  const view = presentNetwork({
    enabled: true, listening: false, disconnected: true, configured: true,
    physical_proof: true, renderer: 'lumen',
    grant_id: 'grant-secret', fingerprint: 'abc', identity: 'secret',
    configuration: {source: 'workspace-network', adapter_kind: 'lan', interface_configured: true, interface_address: '10.0.0.8'},
    peers: [{node_id: 'peer-1', state: 'disconnected', paired: false, invite: 'discovered', disconnected: true, execution_authorized: true}],
  });
  assert.equal(view.available, true);
  assert.equal(view.physical_proof, false);
  assert.equal(view.listening, false);
  assert.equal(view.disconnected, true);
  assert.equal(view.configuration.adapter_kind, 'lan');
  assert.equal(view.configuration.interface_address, undefined);
  assert.equal(view.peers[0].execution_authorized, false);
  assert.equal(JSON.stringify(view).includes('grant-secret'), false);
  assert.equal(JSON.stringify(view).includes('fingerprint'), false);
});

test('a failed optional network read invents no peers', () => {
  const view = presentNetwork({status: 'unavailable', query_failed: true, effect_uncertain: false});
  assert.equal(view.readFailure, true);
  assert.deepEqual(view.peers, []);
  assert.equal(view.available, false);
});

test('a document outside schema 1 is refused without peers', () => {
  const view = presentNetwork({schema: 2, renderer: 'other', dots: [{node_id: 'x'}]});
  assert.equal(view.available, false);
  assert.deepEqual(view.peers, []);
});

test('reads omit request_key and mutations omit bind, host, renderer and grant', () => {
  const home = networkPayload('network_home', {space_id: 's', bind: {port: 1}, host: '127.0.0.1', renderer: 'lumen', grant: 'g'});
  assert.deepEqual(home, {action: 'network_home'});
  const status = networkPayload('network_status', {space_id: 's', dot_id: 'd', request_key: 'should-not-stick'});
  assert.equal(status.request_key, undefined);
  assert.deepEqual(status, {action: 'network_status', space_id: 's', dot_id: 'd'});
  const invite = networkPayload('network_invite', {
    space_id: 's', dot_id: 'd', address: '10.1.1.8', port: '4300', host: '127.0.0.1', bind: {port: 9}, renderer: 'lumen', grant_id: 'grant-1',
  });
  assert.equal(invite.address, '10.1.1.8');
  assert.equal(invite.port, 4300);
  assert.equal(invite.host, undefined);
  assert.equal(invite.bind, undefined);
  assert.equal(invite.renderer, undefined);
  assert.equal(invite.grant_id, undefined);
  assert.equal(typeof invite.request_key, 'string');
  assert.notEqual(invite.request_key, '');
});

test('delegation keeps the artifact in review and drops the grant', () => {
  const shown = presentNetworkResult({
    status: 'committed', grant_id: 'grant-9', fingerprint: 'fp',
    result_document: 'brief', receipt: {work_item_state: 'IN_REVIEW', intent_id: 'intent-1', grant_id: 'grant-9'},
    physical_proof: true,
  });
  assert.equal(shown.ok, true);
  assert.equal(shown.physical_proof, false);
  assert.equal(shown.inReview, true);
  assert.equal(shown.artifact, 'brief');
  assert.equal(shown.grant_id, false);
  assert.equal(shown.mayResend, false);
});
