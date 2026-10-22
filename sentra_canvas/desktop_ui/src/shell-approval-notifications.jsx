import React from 'react';
import { ShellDecisionCenter } from './shell-decisions.jsx';

// Owner-visible persisted requests. Neither polling nor mounting grants access.
// The 3s polling, the inline-conversation filter and the maintenance/reauth
// suppression live in `useDecisionInbox`; this component only preserves the
// historical public API used by `shell-app.jsx`.
export function ShellApprovalNotifications({ bridge, projectId, onOpenConversation, shellError = '', inlineConversationId, onCount }) {
  return <ShellDecisionCenter bridge={bridge} projectId={projectId} inlineConversationId={inlineConversationId}
    onOpenConversation={onOpenConversation} shellError={shellError} onCount={onCount} />;
}
