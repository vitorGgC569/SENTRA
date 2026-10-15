import { test } from 'node:test';
import assert from 'node:assert/strict';
import { classifyLocalUpdateOffer, legacyFrontendOffer, shouldShowUpdateNotice } from '../src/shell-update-trigger.js';

test('frontend source offers only a local compilation', () => {
  const view = classifyLocalUpdateOffer({
    kind: 'local_checkout_code', available: true, revision: '250:700',
    frontend_stale: true, backend_changed: false,
    action: 'apply_code_updates', installed_update_available: false,
  });
  assert.equal(view.action, 'apply_code_updates');
  assert.equal(view.installedRelease, false);
  assert.equal(shouldShowUpdateNotice(view, ''), true);
  assert.equal(shouldShowUpdateNotice(view, '250:700'), false);
  assert.equal(shouldShowUpdateNotice({...view, revision: '260:700'}, '250:700'), true);
});

test('backend edit requires coordinated approval and never claims an installed release', () => {
  const view = classifyLocalUpdateOffer({
    kind: 'local_checkout_code', available: true, revision: '250:800',
    frontend_stale: false, backend_changed: true,
    action: 'apply_full_updates', installed_update_available: false,
  });
  assert.equal(view.action, 'apply_full_updates');
  assert.equal(view.installedRelease, false);
  assert.match(view.explanation, /Canvas/);
});

test('old native window can detect only stale local interface assets', () => {
  const offer = legacyFrontendOffer({
    frontend_stale: true, frontend_source_time_ns: 1234, bundle_time_ns: 1200,
    native_executable_stale: true,
  });
  assert.equal(offer?.action, 'apply_code_updates');
  assert.equal(legacyFrontendOffer({
    frontend_stale: false, frontend_source_time_ns: 1234, bundle_time_ns: 1200,
    native_executable_stale: true,
  }), null);
});

test('no auto update for unchanged, unsupported, unverified or inconsistent status', () => {
  assert.equal(classifyLocalUpdateOffer(null), null);
  assert.equal(classifyLocalUpdateOffer({kind: 'installed_release', available: true, action: 'apply_full_updates'}), null);
  assert.equal(classifyLocalUpdateOffer({kind: 'local_checkout_code', available: false}), null);
  assert.equal(classifyLocalUpdateOffer({
    kind: 'local_checkout_code', available: true, revision: '250:800',
    backend_changed: true, action: 'apply_full_updates', installed_update_available: true
  }), null);
  assert.equal(classifyLocalUpdateOffer({
    kind: 'local_checkout_code', available: true, revision: 'fake<script>',
    backend_changed: true, action: 'apply_full_updates', installed_update_available: false
  }), null);
});
