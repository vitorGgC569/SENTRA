package sentra

import rego.v1

# Example only: owner must replace this contextual veto with real requirements.
# No rule grants SENTRA capabilities.
default allow := false

allow if {
    input.capability == "read"
}

decision := {
    "allow": allow,
    "revision": data.system.bundles["sentra"].manifest.revision,
}

# Official decision_logs.mask_decision path; keep bundle/decision ID metadata.
log_mask contains "/input"
log_mask contains "/result"
log_mask contains "/request_context"
log_mask contains "/nd_builtin_cache"
