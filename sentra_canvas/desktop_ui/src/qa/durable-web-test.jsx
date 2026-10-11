// Isolated QA entry. Uses the production dialog and API; not linked from the app.
import React from 'react';
import { createRoot } from 'react-dom/client';
import { DurableWebDialog } from '../durable-web-dialog';
import '../desktop.css';
createRoot(document.getElementById('root')).render(<DurableWebDialog ws={window.__QA_WORKSPACE_ID} close={() => {}} />);
