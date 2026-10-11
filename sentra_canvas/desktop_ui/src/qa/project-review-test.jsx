// Browser QA harness only; not linked from Canvas production entrypoint.
// Network requests are intercepted by the isolated Playwright fixture.
import React, { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ProjectReviewDialog } from '../project-review-dialog';
import '../desktop.css';

function ProjectQA() {
  const [open, setOpen] = useState(true);
  return <main>
    <button type="button" onClick={() => setOpen(true)}>Abrir revisão QA</button>
    {open && <ProjectReviewDialog ws={window.__QA_WORKSPACE_ID || "qa-workspace"} close={() => setOpen(false)} />}
  </main>;
}
createRoot(document.getElementById('root')).render(<ProjectQA />);
