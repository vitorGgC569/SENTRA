import {test} from 'node:test';
import assert from 'node:assert/strict';
import args from './workspace-fixture-args.cjs';

test('native workspace fixture uses named URL and output with Electron switches retained',()=>{
 assert.deepEqual(args.parseWorkspaceFixtureArgs(['--user-data-dir=C:/qa profile',
  '--fixture-target=http://127.0.0.1:1234/test/workspace-ux.html','--fixture-output=C:/qa output']),
  {target:'http://127.0.0.1:1234/test/workspace-ux.html',output:'C:/qa output'});
});

test('missing, empty or repeated fixture options fail before any fixture is opened',()=>{
 for(const argv of [[],['http://127.0.0.1:1234/test/workspace-ux.html','C:/qa'],
  ['--fixture-target=','--fixture-output=C:/qa'],
  ['--fixture-target=C:/fixture.html','--fixture-output='],
  ['--fixture-target=C:/a.html','--fixture-target=C:/b.html','--fixture-output=C:/qa'],
  ['--fixture-target=C:/a.html','--fixture-output=C:/qa','--fixture-output=C:/other']])
  assert.throws(()=>args.parseWorkspaceFixtureArgs(argv),/Exactly one nonempty/);
});

test('offline workspace fixture retains the existing file target behavior',()=>{
 assert.deepEqual(args.parseWorkspaceFixtureArgs(['--fixture-target=C:/fixture/index.html',
  '--fixture-output=C:/qa']),{target:'C:/fixture/index.html',output:'C:/qa'});
});
