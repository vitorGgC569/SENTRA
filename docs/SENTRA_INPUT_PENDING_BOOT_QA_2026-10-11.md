# QA — control pending and Debian Live, 2026-10-11

## Direct result on existing Dot VM
- Target Dot: Testando Advanced; physical VirtualBox VM fcd974cf-ccdc-5636-b7af-2f96024d5dde.
- Read-only preflight confirmed VM `running`, existing WorkItem, owner full computer access and Live Debian boot item.
- A *single new owner-authorized* human handoff was performed via SENTRA, followed by a *single* Enter scancode press/release through `dot_vm_input`. Physical receipt: `SUCCEEDED`.
- Human control returned to the agent via a separate authenticated `dot_vm_handoff`; status confirmed `holder=agent`, epoch advanced to 9. No physical VM was recreated or deleted.
- Captures: `.tmp/qa-boot-before-20261012.png`, `.tmp/qa-boot-after-20261012.png`.
- The initial menu was exited. Subsequent framebuffer showed kernel graphical driver `vmwgfx` warnings and a static black screen at 1280×800. A later capture was identical. **Guest graphical desktop NOT CONFIRMED**. Do not represent this as Debian XFCE ready. Graphics controller is `VMSVGA`, 3D disabled; diagnosing/altering virtual graphics and rebooting the existing guest remains a separate physical operation requiring authorization.
- Original boot and lease requests from prior QA were not replayed. One distinct new request identity per action was recorded in `.tmp/qa-boot-existing-debian-20261012.json`.

## Frontend control pending defect and fix
- `sentra_canvas/desktop_ui/src/shell-dot-vm.jsx`: previously `mutate` used `pendingRef.current || newRequest`. This could inadvertently reuse a request_key for a *different action*; the pending CTA called `mutate(pending.action)`, which risked re-submitting the same uncertain effect. Meanwhile `canInput` and the handoff button were blocked by unresolved local pending state.
- Now pending effects are **not re-sent**. The new CTA `Verificar estado sem reenviar` calls only read-only `dot_vm_status`. It clears local UI pending when an authenticated lease epoch proves the handoff happened, or proves a later handoff superseded it (old expected_epoch can never reacquire control), or confirms the physical VM exists/runs after old provisioning uncertainty. It preserves the historical uncertain receipt rather than claiming success or deleting it.
- Build `npm run build`: passed and assets materialized.
- Browser tests in isolated Edge with mock bridge (no physical changes): `.tmp/qa_pending_control_reconciliation_20261012.py` and `.tmp/qa_pending_control_superseded_20261012.py`; both passed. Each observed exactly **one** handoff call, read-only state verification, and removal of pending UI control. No replay.
- The service instance continues to serve its desktop assets; user should refresh the app to load UI bundle changes.
- No commits, pushes, resets, VM deletion or reboot.

## Pending
- Debian live graphical boot is blocked/stalled after entering the boot item. The vmwgfx warning alone is not proof of a fatal error (VirtualBox upstream contributors report it can be harmless); however, repeated unchanged framebuffer warrants deliberate graphics/boot investigation. Avoid blind reboots of a user's active guest.
