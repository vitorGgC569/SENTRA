# SENTRA MCP SDK client host

`mcp_host.mjs` is original SENTRA integration code. No SDK implementation was copied.

The optional dependency is the official `@modelcontextprotocol/client` package,
version 2.3.1, matching the inspected local clone package manifest. That package
declares Apache-2.0, Anthropic, PBC. Local reference snapshot:
`third_party/mcp-typescript-sdk`, revision `b022522089a0` as recorded in the study.

The package has not been installed, built or executed during this implementation
phase. Distribution must retain the LICENSE/NOTICE files from the actual pinned
installed package and its transitive dependencies, plus a locked dependency
inventory/SBOM. This notice does not replace those licenses or imply that the
snapshot root's older licensing descriptions apply to every package.

Protocol behavior is based on the clone's official version-negotiation,
subscriptions, server-requests and input-required contracts. The host has no
model provider, no sampling/roots, no automatic tool retry and no automatic
interactive fulfilment. The central SENTRA process controls physical admission.
