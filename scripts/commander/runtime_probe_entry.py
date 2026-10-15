"""Read-only frozen-runtime binding QA. Not part of the installed product."""
import json
import sys


def main():
    if getattr(sys, 'frozen', False) is not True:
        raise RuntimeError('This probe requires the actual frozen executable')
    from sentra_code_mode.artifact_config import load_artifact
    from sentra_code_mode.quickjs_runtime import QuickJSWasmRunner
    from sentra_remote.runtime_payload import installed_hcs_configuration, installed_rustdesk_configuration
    artifact = load_artifact()
    readiness = QuickJSWasmRunner(artifact).readiness()
    if readiness.get('enabled') is not True:
        raise RuntimeError('Installed QuickJS readiness failed')
    hcs = installed_hcs_configuration()
    rustdesk = installed_rustdesk_configuration()
    print(json.dumps({'frozen': True, 'quickjs': {'wasm_sha256': artifact.wasm_sha256,
        'sbom_sha256': artifact.sbom_sha256, 'enabled': readiness['enabled']},
        'hcs': {'bridge_sha256': hcs['bridge_sha256']},
        'rustdesk': {'executable_sha256': rustdesk['executable_sha256'], 'source_revision': rustdesk['source_revision']},
        'grants_created': False, 'native_process_started': False,
        'installed_release_verified': False, 'guest_verified': False}, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
