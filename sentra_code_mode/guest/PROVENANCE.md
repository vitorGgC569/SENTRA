# Provenance — SENTRA QuickJS guest (A08)

The upstream source pin was verified 2026-10-11. The guest is built outside
the checkout by `scripts/commander/build_quickjs.py` using `build.sh`; no binary
is committed here. The ASTRA implementation has now compiled and executed it
in real Wasmtime. `.tmp/astra-quickjs-runtime.json` records 11 acceptance cases;
`docs/ASTRA_IMPLEMENTACAO_E_ACEITE.md` distinguishes these from installed QA.

## Upstream QuickJS source (real, downloaded + hashed)

- Project: QuickJS by Fabrice Bellard / Charlie Gordon, MIT license
  (`https://bellard.org/quickjs/`, repo `https://github.com/bellard/quickjs`)
- Pinned release: **2026-06-04**
- Tarball: `https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz`
- SHA-256: `b376e839b322978313d929fd20663b11ba58b75df5a46c126dd19ea2fa70ad2a`
- Size: **621500** bytes, 67 entries incl. `quickjs.c`, `quickjs.h`,
  `libregexp.c`, `libunicode.c`, `cutils.c`
- Header conformance: every C API used by the guest was grepped verbatim in
  the extracted `quickjs.h` (`JS_NewRuntime`, `JSMallocFunctions`,
  `JS_SetMemoryLimit`, `JS_SetMaxStackSize`, `JS_SetInterruptHandler`,
  `JS_NewContext`, `JS_Eval` + `JS_EVAL_TYPE_GLOBAL`/`JS_EVAL_FLAG_STRICT`,
  `JS_NewCFunction`, `JS_SetPropertyStr`, `JS_GetException`,
  `JS_ToCStringLen2`, `JS_FreeCString`, `JS_NewStringLen`,
  `JS_ThrowRangeError`, `JS_ThrowInternalError`)

## SENTRA guest source (this workspace, hashes at time of writing)

Historical Pacto snapshot below, superseded by Prisma source corrections.
These hashes do not pin the current guest sources. The final pipeline must
hash the current C/platform/header/ABI/inspector/build inputs before shipping.

| File | SHA-256 | Bytes |
|---|---|---|
| `sentra_code_mode/guest/sentra_quickjs_guest.c` | `c5129a9bfdd6cc95d4666842be917702e74f2424ea15ae1e676285005daabf86` | 12422 |
| `sentra_code_mode/guest/ABI.md` | `abba1d3671a1d0e3dfeb3da91de191dc3190a2acdf77d8afec8336f0971c93ba` | 4168 |
| `sentra_code_mode/guest/build.sh` | `5e21cb4f304aa7425e8ce5aba359fb219f7a0489ca9a9458896d7be1ec92a7e5` | 5041 |

## What distribution (Vitra) must ship for `quickjs-wasm` to enable

1. Run `guest/build.sh` with wasi-sdk → `dist/sentra_quickjs_guest.wasm`
   (import allowlist enforced: exactly `env.sentra_host_call`)
2. Ship `dist/` = wasm bytes + generated `sbom.cdx.json` (CycloneDX 1.5) +
   `provenance.json` (wasm SHA, upstream pin, ABI v1, `validated: false`)
3. Set host env pins (`SENTRA_QUICKJS_WASM_PATH/SBOM_PATH/*_SHA256`, see
   `sentra_code_mode/artifact_config.py`) + `pip install wasmtime`
4. Run `tests/qa/astra_quickjs_runtime.py` against those exact artifact bytes.
   This tests the runtime without granting system tools. Then validate actual
   Control Plane tools and the installed journey separately.

## What is explicitly NOT claimed

- The built guest and runtime acceptance do not prove the installed release,
  central tool dispatch, or an arbitrary workload's result quality.
- `readiness()` reports `READY_ABI_V1` only when artifact + wasmtime resolve.
- `bounded-js` is interim (`a08_satisfied: false` on every receipt).

## Prisma source delta (no build/runtime execution)

Host uses mandatory consume_fuel, Store memory/table limits and epoch deadline;
actual worker CPU clock is separate from wall time. ABI is inspected from
exact hashed bytes, with no start function or import/export/type fallback.
Guest has a concrete freeing/splitting/coalescing allocator bounded by whole
linear memory, deterministic context seed and no environment/clock imports.
Build driver links static libc/libm, permits only sentra_host_call unresolved,
copies the upstream MIT license, and runs the nonexecuting ABI reader at the
future build stage. Atomics/pthreads removed from pinned source without
disabling engine stack checks. Tool request length/scratch reuse/attempt count
and C JSON serialization corrected. Current sources require final rebuild;
old binary/pins, if staged separately by root, cannot certify these changes.

## ASTRA build/runtime corrections

The build now compiles pinned `dtoa.c`, removes its unused setjmp header with
an exact checked transformation, and uses wasm32-wasip1 plus upstream signed
overflow/character flags. The C linear stack is 512 KiB so the 256 KiB JS stack
floor does not underflow. Static libc clock/descriptor fallback paths trap
locally; the inspected binary still imports only `env.sentra_host_call`.

Exception classification preserves both the error message and stack, and fuel
exhaustion is checked independently of exception wording. Runtime acceptance
tests actual CPU/wall interruption, memory/result limits, cancellation and
denied host calls. Static libc/compiler-rt licenses and source revisions are
in `licenses/`, copied and hashed into the artifact/SBOM. The build manifest's
`validated: false` is not rewritten by these tests; QA evidence is separate.
