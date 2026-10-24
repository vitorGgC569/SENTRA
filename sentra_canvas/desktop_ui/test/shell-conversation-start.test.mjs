import { test } from 'node:test';
import assert from 'node:assert/strict';
import { conversationTitleFromMessage, matchesConversationStart, homeAttachmentError, recentStartConversations } from '../src/shell-conversation-start.js';

test('conversation title uses the first words and normalizes pasted whitespace', () => {
  assert.equal(conversationTitleFromMessage('  Quero\n  revisar o login do projeto agora com você  '), 'Quero revisar o login do projeto agora com');
  assert.equal(conversationTitleFromMessage('Revisar login'), 'Revisar login');
  assert.equal(conversationTitleFromMessage(' \n '), 'Nova conversa');
  const long = conversationTitleFromMessage('😀'.repeat(100));
  assert.equal(Array.from(long).length, 70);
  assert.ok(long.endsWith('…'));
  assert.equal(long.includes('\ufffd'), false);
});

test('Home stages only nonempty files within the existing upload size budgets', () => {
  assert.ok(homeAttachmentError({name:'empty.txt',type:'text/plain',size:0}));
  assert.equal(homeAttachmentError({name:'report.pdf',type:'application/pdf',size:20*1024*1024}),'');
  assert.ok(homeAttachmentError({name:'report.pdf',type:'application/pdf',size:20*1024*1024+1}));
  assert.equal(homeAttachmentError({name:'photo.png',type:'',size:8*1024*1024}),'');
  assert.ok(homeAttachmentError({name:'photo.png',type:'',size:8*1024*1024+1}));
});

test('recent chats show a newly appended conversation first without reordering the stored collection', () => {
  const rows = [{conversation_id:'old',created_at:1700000000},{conversation_id:'new',updated_at:'2026-10-23T23:00:00Z'},{conversation_id:'missing'}];
  assert.deepEqual(recentStartConversations(rows,2).map(row=>row.conversation_id),['new','old']);
  assert.deepEqual(rows.map(row=>row.conversation_id),['old','new','missing']);
});

test('first-message handoff must match the exact confirmed conversation scope', () => {
  const scope = {project_id:'p',space_id:'s',conversation_id:'c'};
  const start = {...scope,id:'intent-1',content:'Revisar login'};
  assert.equal(matchesConversationStart(start,scope),true);
  for (const field of Object.keys(scope)) assert.equal(matchesConversationStart({...start,[field]:'other'},scope),false);
  assert.equal(matchesConversationStart({...start,content:' '},scope),false);
  assert.equal(matchesConversationStart(null,scope),false);
});
