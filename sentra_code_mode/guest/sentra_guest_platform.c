/* Guest-only bounded allocator and deterministic, I/O-free libc boundaries.
 * No host import, descriptor, environment, clock, entropy or worker is opened.
 * The Wasmtime store independently limits the whole linear memory.
 */
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <sys/time.h>
#include <wasi/api.h>
#include "sentra_guest_platform.h"

extern unsigned char __heap_base;
typedef struct Block { uint32_t size, free; struct Block *next; uint32_t reserved; } Block;
static Block *first = 0, *last = 0;
static uint32_t ceiling = 1048576, frontier = 0;

void sentra_allocator_limit(uint32_t bytes) { ceiling = bytes; }
void *__wrap_malloc(size_t n) {
    if (!n || n > 33554400u) return 0;
    uint32_t size = ((uint32_t)n + 15u) & ~15u;
    for (Block *b = first; b; b = b->next) {
        if (b->free && b->size >= size) {
            if (b->size >= size + sizeof(Block) + 16u) {
                Block *tail = (Block *)((unsigned char *)(b + 1) + size);
                tail->size = b->size - size - sizeof(Block);
                tail->free = 1; tail->next = b->next; tail->reserved = 0;
                if (last == b) last = tail;
                b->next = tail; b->size = size;
            }
            b->free = 0; return b + 1;
        }
    }
    if (!frontier) frontier = ((uint32_t)(uintptr_t)&__heap_base + 15u) & ~15u;
    uint32_t end = frontier + sizeof(Block) + size;
    if (end < frontier || end > ceiling) return 0;
    uint32_t pages = __builtin_wasm_memory_size(0);
    uint32_t needed = (end + 65535u) / 65536u;
    if (needed > pages && __builtin_wasm_memory_grow(0, needed - pages) == (size_t)-1) return 0;
    Block *b = (Block *)(uintptr_t)frontier;
    b->size = size; b->free = 0; b->next = 0; b->reserved = 0;
    if (last) last->next = b; else first = b;
    last = b; frontier = end; return b + 1;
}
void __wrap_free(void *p) {
    if (!p) return;
    Block *b = (Block *)p - 1; b->free = 1;
    for (Block *i = first; i && i->next;) {
        if (i->free && i->next->free) {
            Block *next = i->next;
            i->size += sizeof(Block) + next->size; i->next = next->next;
            if (last == next) last = i;
        } else i = i->next;
    }
}
size_t __wrap_malloc_usable_size(void *p) { return p ? ((Block *)p - 1)->size : 0; }
void *__wrap_realloc(void *p, size_t n) {
    if (!p) return __wrap_malloc(n);
    if (!n) { __wrap_free(p); return 0; }
    size_t old = __wrap_malloc_usable_size(p);
    if (n <= old) return p;
    void *next = __wrap_malloc(n);
    if (next) { memcpy(next, p, old); __wrap_free(p); }
    return next;
}
void *__wrap_calloc(size_t count, size_t size) {
    if (size && count > SIZE_MAX / size) return 0;
    size_t n = count * size;
    void *p = __wrap_malloc(n); if (p) memset(p, 0, n); return p;
}
/* QuickJS seeds Math.random at context creation; the API is then disabled.
 * Fixed sandbox-local initialization performs no host clock access. */
int gettimeofday(struct timeval *tv, void *zone) {
    (void)zone; if (tv) { tv->tv_sec = 0; tv->tv_usec = 0; } return 0;
}
int clock_gettime(clockid_t id, struct timespec *value) {
    (void)id; (void)value; __builtin_trap();
}
char *getenv(const char *name) { (void)name; return 0; }
void abort(void) { __builtin_trap(); }

/* Static libc can retain clock/stdio fallback branches even when the guest
 * only uses memory formatting. Intercept them before linking WASI wrappers:
 * an attempted clock or descriptor access traps locally, never calls a host.
 * The post-link ABI verifier still rejects every WASI import.
 */
__wasi_errno_t __wrap___wasi_clock_time_get(__wasi_clockid_t id,
        __wasi_timestamp_t precision, __wasi_timestamp_t *time) {
    (void)id; (void)precision; (void)time; __builtin_trap();
}
__wasi_errno_t __wrap___wasi_fd_close(__wasi_fd_t fd) {
    (void)fd; __builtin_trap();
}
__wasi_errno_t __wrap___wasi_fd_seek(__wasi_fd_t fd, __wasi_filedelta_t offset,
        __wasi_whence_t whence, __wasi_filesize_t *position) {
    (void)fd; (void)offset; (void)whence; (void)position; __builtin_trap();
}
__wasi_errno_t __wrap___wasi_fd_write(__wasi_fd_t fd,
        const __wasi_ciovec_t *buffers, size_t count, size_t *written) {
    (void)fd; (void)buffers; (void)count; (void)written; __builtin_trap();
}
