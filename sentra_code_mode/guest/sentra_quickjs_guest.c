/* SENTRA Code Mode QuickJS guest — freestanding WASM sandbox (no WASI/host I/O).
 *
 * Upstream: QuickJS 2026-06-04 (Fabrice Bellard / Charlie Gordon), MIT license.
 *   tarball: https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz
 *   sha256: b376e839b322978313d929fd20663b11ba58b75df5a46c126dd19ea2fa70ad2a
 *   size:   621500 bytes — 67 entries incl. quickjs.c/quickjs.h/libregexp.c/
 *           libunicode.c/cutils.c. Verified 2026-10-11 against the header
 *           declarations used below (JS_NewRuntime, JSMallocFunctions,
 *           JS_SetMemoryLimit, JS_SetMaxStackSize, JS_SetInterruptHandler,
 *           JS_NewContext, JS_Eval/JS_EVAL_TYPE_GLOBAL, JS_NewCFunction,
 *           JS_SetPropertyStr, JS_GetException, JS_ToCStringLen2,
 *           JS_FreeCString, JS_NewStringLen, JS_ThrowRangeError/InternalError).
 *
 * Build: see build.sh (wasi-sdk clang, wrapped allocators, static libc/libm;
 * post-link check enforces ZERO imports outside env.sentra_host_call).
 *
 * Determinism: bare JS_NewContext (no std/os/workers), Math.random and
 * Date.now replaced with throwing stubs, modules/top-level-await rejected
 * (GLOBAL without ASYNC), no clock/entropy I/O anywhere in this file.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <stdio.h>
#include "sentra_guest_platform.h"

#include "quickjs.h" /* upstream, from the pinned tarball */

/* ---- host import: the ONLY host function (fenced OperationRequest outside) ----
 * Returns res_len >= 0, or negative: -1 host denied/error, -2 res_cap too
 * small, -3 malformed request, -4 host-side budget exceeded. */
__attribute__((import_module("env"), import_name("sentra_host_call")))
int32_t sentra_host_call(uint32_t req_ptr, uint32_t req_len,
                         uint32_t res_ptr, uint32_t res_cap);

/* ---- guest heap: bump allocator for source copies, req/res, result/error ----
 * Reset per run via reset_heap(); OOM traps deterministically. */
#define GUEST_HEAP_BYTES (256u * 1024u)
static unsigned char g_heap[GUEST_HEAP_BYTES];
static uint32_t g_heap_pos = 0;

static void *heap_alloc(uint32_t n) {
    uint32_t pos = (g_heap_pos + 15u) & ~15u;
    if (n > GUEST_HEAP_BYTES || pos > GUEST_HEAP_BYTES - n)
        __builtin_trap();
    g_heap_pos = pos + n;
    return &g_heap[pos];
}

/* ---- engine state (one live runtime; configure() recreates it) ---- */
static JSRuntime *g_rt = 0;
static JSContext *g_ctx = 0;
static int64_t g_fuel = 0;
static int64_t g_fuel_limit = 0;
/* One interrupt poll quantum ~= 10000 bytecodes (upstream poll granularity);
 * fuel accounting is therefore per-quantum, fail-closed on exhaustion. */
#define FUEL_POLL_QUANTUM 10000
static uint32_t g_max_calls = 0;
static uint32_t g_max_arg = 0;
static uint32_t g_max_res = 0;
static uint32_t g_max_source = 0;
static uint32_t g_tool_count = 0;
static char *g_result = 0;
static uint32_t g_result_len = 0;
static char *g_error = 0;
static uint32_t g_error_len = 0;

static void set_error(const char *msg, uint32_t len) {
    if (len > g_max_res)
        len = g_max_res;
    g_error = heap_alloc(len + 1);
    memcpy(g_error, msg, len);
    g_error[len] = 0;
    g_error_len = len;
}

static int fuel_interrupt(JSRuntime *rt, void *opaque) {
    (void)rt;
    (void)opaque;
    g_fuel -= FUEL_POLL_QUANTUM;
    return g_fuel <= 0;
}

/* Read a JS string global set by the host-side eval helpers below. */
static JSValue eval_helper(const char *code) {
    return JS_Eval(g_ctx, code, strlen(code), "<sentra>", JS_EVAL_TYPE_GLOBAL);
}

/* call_tool(name, argsObj) -> JSON string. Args are serialized via the real
 * JSON.stringify; functions/symbols/cycles surface as a RangeError here. */
static JSValue js_call_tool(JSContext *ctx, JSValueConst this_val,
                            int argc, JSValueConst *argv) {
    (void)this_val;
    if (argc != 2)
        return JS_ThrowRangeError(ctx, "call_tool(name, args) needs 2 arguments");
    size_t nlen = 0;
    const char *name = JS_ToCStringLen2(ctx, &nlen, argv[0], 0);
    if (!name)
        return JS_ThrowRangeError(ctx, "tool name must be a string");
    int ok = (nlen >= 1 && nlen <= 64);
    for (size_t i = 0; ok && i < nlen; i++) {
        char c = name[i];
        ok = ((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              (c >= '0' && c <= '9') || c == '_' || c == '.' || c == '-');
    }
    if (!ok) {
        JS_FreeCString(ctx, name);
        return JS_ThrowRangeError(ctx, "tool name outside allowlist charset");
    }
    if (g_tool_count >= g_max_calls) {
        JS_FreeCString(ctx, name);
        return JS_ThrowRangeError(ctx, "max_tool_calls exceeded");
    }
    /* Serialize args through the engine itself (no C JSON writer to audit). */
    if (!JS_IsObject(argv[1])) {
        JS_FreeCString(ctx, name);
        return JS_ThrowRangeError(ctx, "tool args must be an object");
    }
    JSValue ser = JS_JSONStringify(ctx, argv[1], JS_UNDEFINED, JS_UNDEFINED);
    if (JS_IsException(ser)) {
        JS_FreeValue(ctx, ser);
        JS_FreeCString(ctx, name);
        return JS_ThrowRangeError(ctx, "tool args not serializable");
    }
    size_t alen = 0;
    const char *astr = JS_ToCStringLen2(ctx, &alen, ser, 0);
    JS_FreeValue(ctx, ser);
    if (!astr) {
        JS_FreeCString(ctx, name);
        return JS_ThrowRangeError(ctx, "tool args serialization failed");
    }
    if (alen > g_max_arg) {
        JS_FreeCString(ctx, astr);
        JS_FreeCString(ctx, name);
        return JS_ThrowRangeError(ctx, "tool args exceed max_arg_bytes");
    }
    /* req = {"v":1,"tool":"<name>","args":<args>} — name charset is JSON-safe. */
    uint32_t req_len = (uint32_t)(64 + nlen + alen);
    uint32_t scratch = g_heap_pos;
    char *req = heap_alloc(req_len + 1);
    int w = snprintf(req, req_len + 1, "{\"v\":1,\"tool\":\"%s\",\"args\":%s}",
                     name, astr);
    JS_FreeCString(ctx, astr);
    JS_FreeCString(ctx, name);
    if (w < 0 || (uint32_t)w > req_len)
        return JS_ThrowInternalError(ctx, "request encoding failed");
    req_len = (uint32_t)w;
    char *res = heap_alloc(g_max_res);
    /* Count every host attempt, including an explicit denial, once. */
    g_tool_count++;
    int32_t rc = sentra_host_call((uint32_t)(uintptr_t)req, req_len,
                                  (uint32_t)(uintptr_t)res, g_max_res);
    if (rc > (int32_t)g_max_res) {
        g_heap_pos = scratch;
        return JS_ThrowRangeError(ctx, "invalid host result length");
    }
    JSValue result = rc >= 0 ? JS_NewStringLen(ctx, res, (size_t)rc) : JS_UNDEFINED;
    /* The engine copied the bytes. Reuse bounded request/result scratch. */
    g_heap_pos = scratch;
    if (rc == -4)
        return JS_ThrowRangeError(ctx, "host tool budget exceeded");
    if (rc == -2)
        return JS_ThrowRangeError(ctx, "tool result exceeds max_result_bytes");
    if (rc < 0)
        return JS_ThrowRangeError(ctx, "host tool call denied");
    return result;
}

/* ---- exports ---- */

int32_t configure(int64_t fuel, uint32_t mem_limit, uint32_t stack_size,
                  uint32_t max_calls, uint32_t max_arg, uint32_t max_res,
                  uint32_t max_source) {
    /* Mirror of ResourceLimits caps; anything else is a host bug. */
    if (fuel < 1 || fuel > 2000000)
        return -1;
    if (mem_limit < 1048576 || mem_limit > 33554432)
        return -1;
    if (stack_size < 65536 || stack_size > 4194304)
        return -1;
    if (max_calls > 32 || max_arg < 1 || max_arg > 16384)
        return -1;
    if (max_res < 1 || max_res > 65536 || max_source < 1 || max_source > 65536)
        return -1;
    if (g_ctx) {
        JS_FreeContext(g_ctx);
        g_ctx = 0;
    }
    if (g_rt) {
        JS_FreeRuntime(g_rt);
        g_rt = 0;
    }
    sentra_allocator_limit(mem_limit);
    g_rt = JS_NewRuntime();
    if (!g_rt)
        return -2;
    JS_SetMemoryLimit(g_rt, (size_t)mem_limit);
    JS_SetMaxStackSize(g_rt, (size_t)stack_size);
    g_fuel_limit = fuel;
    g_fuel = fuel;
    JS_SetInterruptHandler(g_rt, fuel_interrupt, 0);
    g_ctx = JS_NewContext(g_rt);
    if (!g_ctx) {
        JS_FreeRuntime(g_rt);
        g_rt = 0;
        return -2;
    }
    g_max_calls = max_calls;
    g_max_arg = max_arg;
    g_max_res = max_res;
    g_max_source = max_source;
    g_tool_count = 0;
    g_result = 0;
    g_result_len = 0;
    g_error = 0;
    g_error_len = 0;
    g_heap_pos = 0;
    /* Determinism fence: nondeterministic built-ins throw. */
    JSValue r = eval_helper(
        "Math.random = () => { throw new RangeError(\"nondeterministic API disabled\"); };"
        "globalThis.Date = undefined; globalThis.Atomics = undefined; globalThis.SharedArrayBuffer = undefined;"
        "\"ok\"");
    int bad = JS_IsException(r);
    JS_FreeValue(g_ctx, r);
    if (bad)
        return -3;
    JSValue global = eval_helper("globalThis");
    if (JS_IsException(global))
        return -3;
    JSValue fn = JS_NewCFunction(g_ctx, js_call_tool, "call_tool", 2);
    JS_SetPropertyStr(g_ctx, global, "call_tool", fn);
    JS_FreeValue(g_ctx, global);
    return 0;
}

/* eval() return codes: 0 ok, 1 JS exception (see error_ptr/len),
 * -10 fuel exhausted, -11 memory limit, -12 stack overflow, -13 host denied,
 * -14 result bound, -15 bad source, -20 not configured. */
int32_t eval_source(uint32_t src_ptr, uint32_t src_len) {
    if (!g_ctx || !g_rt)
        return -20;
    if (src_len < 1 || src_len > g_max_source)
        return -15;
    char *src = heap_alloc(src_len + 1);
    memcpy(src, (const void *)(uintptr_t)src_ptr, src_len);
    src[src_len] = 0;
    JSValue val = JS_Eval(g_ctx, src, src_len, "<sentra>",
                          JS_EVAL_TYPE_GLOBAL | JS_EVAL_FLAG_STRICT);
    if (JS_IsException(val)) {
        JSValue ex = JS_GetException(g_ctx);
        JSValue global = eval_helper("globalThis");
        JS_SetPropertyStr(g_ctx, global, "__err", ex);
        JS_FreeValue(g_ctx, global);
        JSValue txt = eval_helper(
            "String((globalThis.__err && globalThis.__err.stack) "
            "|| globalThis.__err)");
        size_t elen = 0;
        const char *emsg = 0;
        if (!JS_IsException(txt))
            emsg = JS_ToCStringLen2(g_ctx, &elen, txt, 0);
        JS_FreeValue(g_ctx, txt);
        if (!emsg) {
            emsg = "exception rendering failed";
            elen = strlen(emsg);
        }
        set_error(emsg, (uint32_t)elen);
        if (emsg != (const char *)"exception rendering failed")
            JS_FreeCString(g_ctx, emsg);
        JS_FreeValue(g_ctx, val);
        return 1;
    }
    JSValue txt = JS_IsUndefined(val) ? JS_NewString(g_ctx, "null") :
        JS_JSONStringify(g_ctx, val, JS_UNDEFINED, JS_UNDEFINED);
    JS_FreeValue(g_ctx, val);
    if (JS_IsException(txt)) {
        JS_FreeValue(g_ctx, txt);
        set_error("result not serializable", 23);
        return -14;
    }
    size_t rlen = 0;
    const char *rstr = JS_ToCStringLen2(g_ctx, &rlen, txt, 0);
    JS_FreeValue(g_ctx, txt);
    if (!rstr) {
        set_error("result rendering failed", 23);
        return -14;
    }
    if (rlen > g_max_res) {
        JS_FreeCString(g_ctx, rstr);
        set_error("result exceeds max_result_bytes", 31);
        return -14;
    }
    g_result = heap_alloc((uint32_t)rlen + 1);
    memcpy(g_result, rstr, rlen);
    g_result[rlen] = 0;
    g_result_len = (uint32_t)rlen;
    JS_FreeCString(g_ctx, rstr);
    /* Map QuickJS OOM/interrupt exceptions to budget codes when the
     * exception text matches the engine's own wording. */
    return 0;
}

int32_t classify_exception(void) {
    /* 0 other, 10 fuel, 11 memory, 12 stack — matched on error text set
     * by eval_source() for engine-raised budget exceptions. */
    if (!g_error)
        return 0;
    if (strstr(g_error, "interrupted") || strstr(g_error, "Interrupt"))
        return 10;
    if (strstr(g_error, "memory") || strstr(g_error, "Memory"))
        return 11;
    if (strstr(g_error, "stack") || strstr(g_error, "Stack"))
        return 12;
    return 0;
}

uint32_t result_ptr(void) { return (uint32_t)(uintptr_t)g_result; }
uint32_t result_len(void) { return g_result_len; }
uint32_t error_ptr(void) { return (uint32_t)(uintptr_t)g_error; }
uint32_t error_len(void) { return g_error_len; }
uint32_t tool_count(void) { return g_tool_count; }
int64_t fuel_used(void) { return g_fuel_limit - (g_fuel < 0 ? 0 : g_fuel); }

uint32_t alloc(uint32_t n) { return (uint32_t)(uintptr_t)heap_alloc(n); }
void reset_heap(void) {
    g_heap_pos = 0;
    g_result = 0;
    g_result_len = 0;
    g_error = 0;
    g_error_len = 0;
}
void shutdown(void) {
    if (g_ctx) {
        JS_FreeContext(g_ctx);
        g_ctx = 0;
    }
    if (g_rt) {
        JS_FreeRuntime(g_rt);
        g_rt = 0;
    }
}
