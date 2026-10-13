/*!
 * Adapted from CopilotKit/OpenDots src/client/Mascot.tsx
 * commit 625452e06cde74cb25b0ce319e2c1be0488f5a5f.
 * Copyright (c) Atai Barkai. MIT License.
 * Full permission notice: ./assets/opendots/LICENSE.
 * Changes: JSX, imported pinned assets, Portuguese labels and SENTRA status mapping.
 */
import React from 'react';
import blue from './assets/opendots/blue.png';
import mint from './assets/opendots/mint.png';
import orange from './assets/opendots/orange.png';
import purple from './assets/opendots/purple.png';

const characters = [blue, mint, orange, purple];
export const DOT_MASCOTS = [
  { id: 'blue', label: 'Azul', image: blue }, { id: 'mint', label: 'Verde', image: mint },
  { id: 'orange', label: 'Laranja', image: orange }, { id: 'purple', label: 'Roxo', image: purple },
];
function characterFor(identity) {
  if (!identity) return characters[0];
  let hash = 0;
  for (const character of identity) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return characters[hash % characters.length];
}
export function mascotFor(identity) {
  return DOT_MASCOTS.find(item => item.image === characterFor(identity)).id;
}
function presentationState(status) {
  const value = String(status || 'idle').toLowerCase();
  if (['running', 'working', 'active'].includes(value)) return 'working';
  if (['waiting_approval', 'waiting_chatgpt_user_approval', 'needs_input', 'uncertain'].includes(value)) return 'needs-input';
  if (['paused', 'stopped', 'interrupted', 'cancelled'].includes(value)) return 'paused';
  if (['completed', 'succeeded'].includes(value)) return 'complete';
  return 'idle';
}
export function DotMascot({ identity, mascot, name = 'Dot', status, size = 'small', decorative = false }) {
  return <span className={'shell-mascot ' + size + ' ' + presentationState(status)}>
    <img src={DOT_MASCOTS.find(item => item.id === mascot)?.image || characterFor(identity)} alt={decorative ? '' : name + (status ? ' · ' + status : '')}
      width={512} height={512} draggable={false} />
  </span>;
}
