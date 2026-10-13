#ifndef SENTRA_GUEST_PLATFORM_H
#define SENTRA_GUEST_PLATFORM_H
#include <stddef.h>
#include <stdint.h>
void sentra_allocator_limit(uint32_t bytes);
size_t malloc_usable_size(void *ptr);
#endif
