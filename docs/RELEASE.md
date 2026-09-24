# SENTRA Desktop release process

Stable desktop releases use semantic tags `vX.Y.Z`. The tag must match
`PRODUCT_VERSION` in `sentra_version.py`.

The MCP protocol/server version remains independently versioned as
`SERVER_VERSION`; a Desktop release does not silently change the MCP protocol.

## Required GitHub secrets

Configure these repository/environment secrets before creating a stable tag:

- `WINDOWS_CERTIFICATE_B64` — Base64-encoded PFX containing the Authenticode certificate.
- `WINDOWS_CERTIFICATE_PASSWORD` — PFX password.

Optional repository variable:

- `WINDOWS_TIMESTAMP_URL` — RFC 3161 timestamp server.

Never commit the PFX or its password.
## Build order

The release workflow intentionally uses this order:

1. run the full test suite;
2. build payload executables;
3. Authenticode-sign every payload executable;
4. build `SENTRA-Setup.exe` with the signed payload embedded;
5. sign Setup;
6. download the pinned official OpenAI tunnel-client and verify SHA-256;
7. generate the MSI and update ZIP;
8. sign the MSI;
9. regenerate the release manifest, SBOM and checksums after signing;
10. verify Authenticode and SHA-256;
11. run packaged smoke/installation checks;
12. create the immutable GitHub Release for the tag.

A stable tag fails if the signing certificate is missing.
## Local release-candidate build

A developer can build unsigned artifacts for testing:

```powershell
python scripts/commander/build_windows.py --clean-output --phase all
python scripts/commander/release_assets.py --tunnel-archive .sentra/tunnel-client/tunnel-client-v0.0.14-windows-amd64.zip
```

Unsigned local artifacts are test candidates only. They must not be presented
as a stable SENTRA release.

## Upgrade and rollback

The Desktop reads `release-manifest.json` over HTTPS. Stable automatic updates
require both the advertised SHA-256 and the expected Authenticode signer.

The updater keeps the previous install in a dedicated rollback directory. If
Setup fails, rollback is automatic. After a successful update, the Desktop
offers **Rollback previous version** until that backup is replaced by a later
successful update.
