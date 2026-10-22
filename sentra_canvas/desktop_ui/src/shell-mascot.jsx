/*!
 * Adapted from CopilotKit/OpenDots src/client/Mascot.tsx
 * commit 625452e06cde74cb25b0ce319e2c1be0488f5a5f.
 * Copyright (c) Atai Barkai. MIT License.
 * Full permission notice: ./assets/opendots/LICENSE.
 * Changes: JSX, imported pinned assets, Portuguese labels and SENTRA status mapping.
 */
import React, { useState } from 'react';
import { mascotMotionState } from './dot-motion';
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
function presentationState(status, execution) { return mascotMotionState(status, execution); }
export function DotMascot({ identity, mascot, name = 'Dot', status, execution, size = 'small', decorative = false }) {
  const source = DOT_MASCOTS.find(item => item.id === mascot)?.image || characterFor(identity);
  const [failedSource, setFailedSource] = useState(null);
  const [retry, setRetry] = useState(null);
  const retrying=retry===source;
  return <span className={'shell-mascot ' + size + ' ' + presentationState(status, execution)} data-state={presentationState(status, execution)}>
    {failedSource === source ? <span className="shell-mascot-fallback" aria-hidden={decorative || undefined}
      role={decorative ? undefined : 'img'} aria-label={decorative ? undefined : name}>D</span> :
      <img src={retrying?source+(source.includes('?')?'&':'?')+'sentra-image-retry=1':source} alt={decorative ? '' : name + (status ? ' · ' + status : '')}
        onError={() => {if(!retrying)setRetry(source);else setFailedSource(source)}} width={512} height={512} draggable={false} />}
  </span>;
}
