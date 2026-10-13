/** Future document gate acceptance cases; not executed during implementation. */
import test from 'node:test';
import assert from 'node:assert/strict';
import * as Y from 'yjs';
import {PrecommitGate} from '../precommit.mjs';
import {documentProjection, initializeDocument} from '../document_policy.mjs';

const name='sentra-document:v1:project:document';
function seed() {
  const doc=new Y.Doc();initializeDocument(doc,Y,name);
  doc.getMap('metadata').set('title','Rich');doc.getMap('metadata').set('format','markdown');
  doc.getText('content').insert(0,'Original');return doc;
}
function update(doc, callback) {
  const vector=Y.encodeStateVector(doc), candidate=new Y.Doc();
  initializeDocument(candidate,Y,name);Y.applyUpdate(candidate,Y.encodeStateAsUpdate(doc));
  callback(candidate);const binary=Y.encodeStateAsUpdate(candidate,vector);candidate.destroy();return binary;
}
test('document precommit waits for authoritative receipt before applying candidate',async()=>{
  const doc=seed();let release, entered;
  const started=new Promise(resolve=>{entered=resolve;});
  const barrier=new Promise(resolve=>{release=resolve;});
  const context={workspaceId:'project',spaceId:'space',documentId:'document',principalId:'alice',epoch:1};
  const connection={context,readOnly:false};let request;
  const gate=new PrecommitGate({authorize:async()=>true,commitSnapshot:async p=>{
    request=p;entered();await barrier;return {revision:2,receipt_id:'receipt'};
  }});gate.setRevision(name,1);
  const pending=gate.authorizeSync({context,connection,documentName:name,document:doc,type:2,
    payload:update(doc,c=>c.getText('content').insert(8,' concurrent'))});
  await started;assert.equal(doc.getText('content').toString(),'Original');
  assert.equal(request.documentId,'document');assert.match(request.mutation_id,/^yjs-[a-f0-9]{64}$/);
  release();await pending;gate.finish(connection);doc.destroy();
});
test('document schema rejects authority roots and readonly mutation',async()=>{
  const doc=seed();const context={workspaceId:'project',documentId:'document',epoch:1};
  const connection={context,readOnly:true};
  const gate=new PrecommitGate({authorize:async()=>true,commitSnapshot:async()=>{throw Error('must not commit');}});
  gate.setRevision(name,1);
  await assert.rejects(gate.authorizeSync({context,connection,documentName:name,document:doc,type:2,
    payload:update(doc,c=>c.getText('content').insert(0,'forbidden'))}));
  doc.getMap('Grant').set('write',true);assert.throws(()=>documentProjection(doc,Y));doc.destroy();
});
test('undo tracks user origin without erasing another user text',()=>{
  const doc=seed(), text=doc.getText('content'), local={local:true};
  const undo=new Y.UndoManager(text,{trackedOrigins:new Set([local])});
  doc.transact(()=>text.insert(0,'Mine '),local);undo.stopCapturing();
  doc.transact(()=>text.insert(text.length,' Theirs'),{remote:true});
  undo.undo();assert.equal(text.toString(),'Original Theirs');
  const relative=Y.createRelativePositionFromTypeIndex(text,2);
  doc.transact(()=>text.insert(0,'prefix '),{remote:true});
  assert.equal(Y.createAbsolutePositionFromRelativePosition(relative,doc).index,9);
  undo.destroy();doc.destroy();
});
