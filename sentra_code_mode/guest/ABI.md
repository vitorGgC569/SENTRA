# SENTRA QuickJS guest ABI v1 (exact — implemented by `sentra_quickjs_guest.c`)

Owner: Pacto. This ABI is DEFINED by real guest source, not assumed: every
entry below has a matching implementation in the guest C and a matching
marshaler in `sentra_code_mode/quickjs_runtime.py`. If guest and host ever
disagree, the build's ABI self-check (see build.sh) fails.

## Linear memory

Single exported `memory` (little-endian, 32-bit pointers). All pointers below
are guest-memory offsets. Guest heap buffers are reset per run
(`reset_heap`); the host never retains guest pointers across calls.

## Host import (exactly one — no WASI, no other host surface)

`env.sentra_host_call(req_ptr: i32, req_len: i32, res_ptr: i32, res_cap: i32) -> i32`

- Request bytes (UTF-8 JSON, `req_len` 1..`64 + 64 + max_arg_bytes`):
  `{"v":1,"tool":"<name>","args":<args-object>}` where `name` matches
  `[A-Za-z0-9_.-]{1,64}` (JSON-safe by construction, no escaping needed).
- Host performs the fenced central `OperationRequest` (`code-tool:<name>`)
  OUTSIDE the sandbox and writes result JSON into `[res_ptr, res_ptr+res_cap)`.
- Return: `res_len >= 0` on success; negative codes:
  `-1` host denied/error (incl. grant denied, unknown tool),
  `-2` `res_cap` too small for the result,
  `-3` malformed request/envelope,
  `-4` host-side budget exceeded.
- The guest maps every negative code to a JS `RangeError`; error text never
  crosses the boundary (codes only — no secret/log leak surface).

## Guest exports

| Export | Signature | Semantics |
|---|---|---|
| `memory` | memory | the single linear memory |
| `configure` | `(fuel: i64, mem_limit, stack_size, max_calls, max_arg, max_res, max_source: i32) -> i32` | `(re)creates runtime+context, sets `JS_SetMemoryLimit`, `JS_SetMaxStackSize`, interrupt fuel, neutralizes `Math.random`/`Date.now`, installs `call_tool`. Returns `0` ok, negative on bad args (`-1`) or engine failure (`-2`, `-3`). Ranges mirror `ResourceLimits` caps; anything else is a host bug. |
| `eval_source` | `(src_ptr, src_len: i32) -> i32` | `0` ok (see `result_*`), `1` JS exception (see `error_*`), `-10` fuel exhausted, `-11` memory limit, `-12` stack overflow, `-13` host denied during run, `-14` result bound/serialization, `-15` source outside bounds, `-20` not configured. Evaluates `JS_EVAL_TYPE_GLOBAL \| JS_EVAL_FLAG_STRICT` (no modules, no top-level await). |
| `classify_exception` | `() -> i32` | `0` other, `10` fuel, `11` memory, `12` stack (matched on engine wording). |
| `result_ptr` / `result_len` | `() -> i32` | JSON bytes of completion value (`undefined` → `null`), `<= max_result_bytes` (else `-14`). |
| `error_ptr` / `error_len` | `() -> i32` | UTF-8 error text (`String(err.stack \|\| err)`), truncated to `max_result_bytes`. |
| `tool_count` | `() -> i32` | host call attempts, including explicit denials (host cross-checks). |
| `fuel_used` | `() -> i64` | `fuel_limit - fuel_remaining` in poll quanta of ~10000 bytecodes. |
| `alloc` | `(n: i32) -> i32` | bump-allocates `n` bytes (16-aligned); OOM traps deterministically. |
| `reset_heap` | `() -> ()` | resets heap and clears result/error views. |
| `shutdown` | `() -> ()` | frees context+runtime. |

## JS surface inside the sandbox

- Exactly one extra global: `call_tool(name: string, args: object) -> string`
  (raw result JSON; user code applies `JSON.parse`). Args serialized via the
  engine's own `JSON.stringify`; unserializable args (cycles, functions) raise
  `RangeError` before any host contact. Name charset enforced in C.
- `Math.random` throws `RangeError("nondeterministic API disabled")`; `Date`,
  `Atomics` and `SharedArrayBuffer` are unavailable.
- No host module loader, `require`, std/os/workers/timers/fetch or host-side
  Python/Node evaluation. ECMAScript evaluation inside the guest stays within
  the same bounded WASM store and cannot acquire another host surface.

## Bounds mapping (ResourceLimits → guest)

`fuel` → interrupt quanta; `memory_bytes` → `JS_SetMemoryLimit` (fail-closed
by the engine); `cpu_milliseconds` → actual worker CPU accounting
(Windows GetThreadTimes / POSIX pthread CPU clock) + epoch interruption;
`wall_milliseconds` → host epoch/watchdog (guest has no clock by design);
`max_source_bytes`/`max_result_bytes`/`max_tool_calls`/`max_arg_bytes` →
`configure()` + C checks; JS stack fixed at 256 KiB via `configure`, inside a
512 KiB C linear stack. The latter includes native frames outside JS execution.
