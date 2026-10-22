import {test} from 'node:test';
import assert from 'node:assert/strict';
import {randomBytes} from 'node:crypto';
import nacl from 'tweetnacl';
import {primitives} from '../src/primitives';
import {ServerSession} from '../src/server-session';
import {PairedE2EEV2ClientSession} from '../src/vendor/paired-e2ee-v2-client-session';

const p=primitives(n=>new Uint8Array(randomBytes(n)));
function pair(){const host=nacl.box.keyPair();const client=PairedE2EEV2ClientSession.create({primitives:p,desktopPublicKeyB64:p.encodeBase64(host.publicKey),transport:'direct'});const server=new ServerSession(client.hello,host.secretKey,host.publicKey,p);assert.equal(client.acceptReady(server.ready),true);return {client,server};}
test('ORCA v2 transport encrypts in both directions and rejects replay',()=>{const {client,server}=pair();const frame=client.sealText('private message');assert.equal(frame.includes('private message'),false);assert.equal(server.open(frame),'private message');assert.equal(server.open(frame),null);const reply=server.seal('protected result');assert.equal(client.openText(reply),'protected result');assert.equal(client.openText(reply),null);});
test('host pinning, session epochs and tamper detection',()=>{const first=pair(),second=pair();const frame=first.client.sealText('one operation');assert.equal(second.server.open(frame),null);const bytes=p.decodeBase64(frame);bytes[bytes.length-1]^=1;assert.equal(first.server.open(p.encodeBase64(bytes)),null);assert.equal(first.server.open(frame),'one operation');const other=nacl.box.keyPair();const impostor=new ServerSession(first.client.hello,other.secretKey,other.publicKey,p);assert.equal(first.client.acceptReady(impostor.ready),false);});
