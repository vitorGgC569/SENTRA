"""Identify experimental sources and the separately generated validation outputs."""
import hashlib
import json
from datetime import datetime,timezone
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[2]
GROUPS=('sentra_canvas/desktop_ui/src/workspace','integrations/orca-mobile/app/components',
        'integrations/orca-mobile/transport/src','integrations/orca-terminal/src',
        'integrations/orca-terminal/scripts','integrations/orca-terminal/vendor',
        'integrations/orca-mobile/app/terminal','integrations/orca-mobile/app/scripts')
FILES=('sentra_canvas/desktop_ui/src/shell-app.jsx','sentra_canvas/desktop_ui/src/shell-bridge.js',
       'sentra_canvas/desktop_ui/qa/orca-workspace.html','sentra_canvas/desktop_ui/qa/orca-workspace.jsx',
       'sentra_canvas/desktop_ui/qa/orca-preview-api.js','sentra_canvas/desktop_ui/vite.orca-preview.config.js',
       'sentra_canvas/desktop_ui/package.json','sentra_canvas/pty_daemon.py','sentra_canvas/pty_client.py','sentra_canvas/mobile_devices.py',
       'sentra_canvas/mobile_host.py','sentra_canvas/mobile_network.py','sentra_canvas/pty_history.py',
       'sentra_canvas/terminal_snapshots.py','sentra_canvas/terminal_frames.py','sentra_canvas/evaluation.py','sentra_canvas/electron_host.py',
       'sentra_canvas/terminal_observation.py','sentra_canvas/terminal_input_receipts.py','sentra_canvas/shell_machines.py',
       'sentra_canvas/desktop_ui/src/terminal-input-journal.js','sentra_canvas/desktop_ui/src/terminal-input-notice.jsx',
       'sentra_canvas/shell_dot_computer.py','sentra_canvas/shell_environment.py',
       'sentra_canvas/workspace_access.py','sentra_canvas/shell_dot_canvas.py','sentra_canvas/shell_access.py',
       'sentra_canvas/workspace_presentation.py','sentra_canvas/permission_presentation.py',
       'sentra_canvas/conversation_permission_status.py','sentra_canvas/shell_approval_inbox.py',
       'sentra_canvas/shell_runtime.py','sentra_canvas/task_runtime.py','sentra_canvas/full_access.py',
       'sentra_canvas/task_verification.py','sentra_canvas/task_presentation.py','sentra_canvas/dot_tool_receipts.py',
       'sentra_canvas/task_workspace.py','sentra_canvas/workspace_file_editor.py','workspace/worktree_review.py',
       'sentra_canvas/desktop_ui/src/document-code-editor.jsx',
       'sentra_executors/_base.py','sentra_executors/workspace_files.py',
       'sentra_runtime/task_lifecycle.py','sentra_canvas/desktop_ui/src/shell-receipts.jsx','sentra_executors/local_computer.py','sentra_cli/agent.py',
       'sentra_canvas/desktop_ui/src/shell-conversation.jsx','sentra_canvas/desktop_ui/src/shell-access.jsx',
       'sentra_canvas/desktop_ui/src/shell-permission-cards.jsx','sentra_canvas/desktop_ui/src/shell-conversation-tools.jsx','sentra_canvas/desktop_ui/src/shell-draft-staging.js',
       'sentra_canvas/desktop_ui/src/shell-approval-notifications.jsx',
       'sentra_canvas/desktop_ui/src/shell-decisions.js','sentra_canvas/desktop_ui/src/shell-decisions.jsx',
       'sentra_canvas/desktop_ui/src/shell-decisions.css',
        'sentra_canvas/desktop_ui/src/shell-decision-requests.js',
        'sentra_canvas/desktop_ui/src/shell-completion-evidence.js',
        'sentra_canvas/desktop_ui/src/shell-event-target.js',
        'sentra_canvas/desktop_ui/src/shell-coucou-macos.css',
       'sentra_canvas/desktop_ui/src/shell-island.jsx','sentra_canvas/desktop_ui/src/shell-island-state.js',
       'sentra_canvas/desktop_ui/src/shell-island.css',
       'sentra_canvas/desktop_ui/src/shell-chat-visuals.js','sentra_canvas/desktop_ui/src/shell-chat-visuals.jsx',
       'sentra_canvas/desktop_ui/src/shell-chat-visuals.css',
       'sentra_canvas/desktop_ui/src/shell-hub.jsx','sentra_canvas/desktop_ui/src/shell-hub-state.js',
       'sentra_canvas/desktop_ui/src/shell-hub.css',
       'sentra_canvas/desktop_ui/src/shell-drop-overlay.jsx','sentra_canvas/desktop_ui/src/shell-drop-overlay.css',
       'sentra_canvas/desktop_ui/src/shell-attachments.jsx',
       'sentra_canvas/desktop_ui/src/shell-dot-vm.jsx',
       'sentra_canvas/desktop_ui/src/shell-dot-computer.jsx',
       'sentra_electron/main.cjs','sentra_electron/presence-window.cjs','sentra_electron/presence-preload.cjs',
       'sentra_electron/desktop-lifecycle.cjs','sentra_canvas/process_lifetime.py',
       'sentra_canvas/desktop_ui/scripts/build-island.mjs',
       'sentra_electron/island-preload.cjs','sentra_canvas/desktop_ui/src/desktop-presence.js',
       'sentra_canvas/desktop_ui/src/desktop-island.jsx','sentra_canvas/desktop_ui/src/desktop-island-entry.jsx',
       'sentra_canvas/desktop_ui/src/desktop-island.css',
       'sentra_canvas/desktop_ui/island.html','sentra_canvas/desktop_ui/vite.island.config.js',
       'sentra_electron/policy.cjs','sentra_electron/evaluation_diagnostics.cjs',
       'sentra_canvas/desktop_ui/src/shell-mascot.jsx','sentra_canvas/desktop_ui/src/dot-companion-engine.js',
       'sentra_canvas/desktop_ui/src/dot-companion.css','sentra_canvas/desktop_ui/src/terminal-checkpoint.js',
       'integrations/orca-terminal/package.json','integrations/orca-terminal/package-lock.json',
       'integrations/orca-terminal/provenance.json',
       'sentra_canvas/workspace_contract.py','sentra_canvas/workspace_requests.py',
       'sentra_canvas/shell_requests.py','sentra_canvas/native_entry.py',
       'sentra_canvas/service.py','sentra_canvas/store.py','sentra_canvas/shell_dot_vm.py','sentra_canvas/__main__.py',
       'sentra_canvas/agent_bindings.py','sentra_canvas/terminal.py','sentra_cli/canvas.py',
       'sentra_cli/canvas_binding.py','sentra_cli/authority_environment.py',
       'sentra_canvas/desktop_ui/src/terminal-pool.js','sentra_canvas/desktop_ui/src/terminal-history-state.js',
       'sentra_canvas/desktop_ui/src/nodes.jsx',
       'sentra_canvas/shell_actor.py','sentra_executors/virtualbox_vm.py',
       'sentra_runtime/machine_host.py','sentra_runtime/orchestration_observation.py','workspace/worktrees.py',
       'sentra_executors/git_worktrees.py','sentra_executors/input_control.py','sentra_executors/playwright_browser.py',
       'sentra_interop/acp_provider.py','sentra_interop/acp_dialects.py','integrations/orca-mobile/app/App.tsx',
       'integrations/orca-mobile/app/app.json','integrations/orca-mobile/app/metro.config.js',
       'integrations/orca-mobile/app/package-lock.json','integrations/orca-mobile/transport/package-lock.json',
       'integrations/opencode/package-lock.json','integrations/opencode/acp_host.py',
       'sentra_canvas/desktop_ui/package-lock.json','integrations/orca-mobile/app/package.json',
       'integrations/orca-mobile/transport/package.json',
       'vendor/orca/provenance.json','vendor/orca/upstream-review.json',
       'vendor/coucou/LICENSE','vendor/coucou/provenance.json')


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    paths={ROOT/path for path in FILES}
    for group in GROUPS:paths.update(p for p in (ROOT/group).rglob('*') if p.is_file())
    sources={p.relative_to(ROOT).as_posix():digest(p) for p in sorted(paths)}
    desktop=ROOT/'sentra_canvas/desktop_ui/.tmp/orca-workspace-build'
    outputs=[p for p in desktop.rglob('*') if p.is_file()]
    preview=ROOT/'sentra_canvas/desktop_ui/.tmp/orca-visual-preview'
    outputs.extend(p for p in preview.rglob('*') if p.is_file())
    outputs.extend(ROOT/'integrations/orca-terminal/dist'/name for name in ('engine.cjs','manifest.json'))
    for platform in ('android','ios'):
        bundles=list((ROOT/'integrations/orca-mobile/app/dist/_expo/static/js'/platform).glob('*.hbc'))
        if len(bundles)!=1:raise ValueError('build each mobile platform before identifying the output')
        outputs.extend(bundles)
    output_records={p.relative_to(ROOT).as_posix():{'sha256':digest(p),'bytes':p.stat().st_size} for p in outputs}
    fingerprint=hashlib.sha256(json.dumps({'sources':sources,'outputs':output_records},sort_keys=True).encode()).hexdigest()
    result={'schema':1,'build_id':'sentra-orca-experimental-'+fingerprint[:12],
        'created_utc':datetime.now(timezone.utc).isoformat(),'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'orca_commit':'70b2197c97b164b16c618736a107967295e5af92','sources':sources,
        'outputs':output_records,
        'native_signed_installers':False,'physical_mobile_homologation':False,'production_activated':False}
    target=ROOT/'vendor/orca/validation-build.json'
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(result['build_id'])


if __name__=='__main__':main()
