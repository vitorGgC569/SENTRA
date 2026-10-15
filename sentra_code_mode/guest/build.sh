#!/usr/bin/env bash
# Build the SENTRA QuickJS guest (real executable WASM) — owner: Pacto.
# Distribution wiring (Vitra) runs this; the checked-in provenance pins inputs.
# Build proof and runtime acceptance are separate; neither is inferred from
# the presence of this driver or a successful C compilation.
set -euo pipefail

UPSTREAM_URL="https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz"
UPSTREAM_SHA256="b376e839b322978313d929fd20663b11ba58b75df5a46c126dd19ea2fa70ad2a"
UPSTREAM_SIZE="621500"
WASI_SDK="${WASI_SDK:-/opt/wasi-sdk}"   # provides clang + wasm-ld + wasi-libc
OUT_DIR="${OUT_DIR:-dist}"
GUEST_DIR="$(cd "$(dirname "$0")" && pwd)"
GUEST_SRC="$GUEST_DIR/sentra_quickjs_guest.c"
ABI_DOC="$GUEST_DIR/ABI.md"

mkdir -p "$OUT_DIR" build-tmp
OUT_DIR="$(cd "$OUT_DIR" && pwd)"
cd build-tmp

# 1. Pinned upstream source (fail closed on any byte difference).
if [ ! -f quickjs-2026-06-04.tar.xz ]; then
  curl -sSL --retry 2 -o quickjs-2026-06-04.tar.xz "$UPSTREAM_URL"
fi
echo "$UPSTREAM_SHA256  quickjs-2026-06-04.tar.xz" | sha256sum -c -
[ "$(stat -c%s quickjs-2026-06-04.tar.xz)" = "$UPSTREAM_SIZE" ]
tar -xf quickjs-2026-06-04.tar.xz
UQ="$PWD/quickjs-2026-06-04"
# Disable only native Atomics/pthreads; preserve QuickJS stack limitation.
python3 - "$UQ/quickjs.c" "$UQ/dtoa.c" <<'EOF'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
source = path.read_text()
if source.count('#define CONFIG_ATOMICS') != 1:
    raise SystemExit('pinned QuickJS Atomics boundary changed')
path.write_text(source.replace('#define CONFIG_ATOMICS', '/* SENTRA: no native threads/Atomics */'))
# This pinned dtoa source includes setjmp.h but uses no setjmp API. WASI
# rejects that unused header unless exception support is enabled. Remove only
# the unused include; fail if upstream ever starts using nonlocal jumps.
dtoa = pathlib.Path(sys.argv[2])
source = dtoa.read_text()
include = '#include <setjmp.h>'
if source.count(include) != 1 or re.search(r'\b(?:setjmp|longjmp|jmp_buf)\b', source.replace(include, '')):
    raise SystemExit('pinned dtoa setjmp boundary changed')
dtoa.write_text(source.replace(include, '/* SENTRA: unused setjmp header omitted for WASM */'))
EOF

# 2. Compile upstream (hosted headers, static libc/libm) + guest, wasm32-wasi.
#    Allocators are wrapped to the guest pool; no syscall may survive linking.
CLANG="$WASI_SDK/bin/clang"
if [ -f "$CLANG.exe" ]; then CLANG="$CLANG.exe"; fi
"$CLANG" --version > compiler.txt
CC=("$CLANG" "--sysroot=$WASI_SDK/share/wasi-sysroot")
CFLAGS=(--target=wasm32-wasip1 -O2 -ffreestanding -fno-builtin -fwrapv -funsigned-char -Wall -Wextra -DNDEBUG
  '-DCONFIG_VERSION="2026-06-04-sentra"' -DCONFIG_BIGNUM=0
  "-I$UQ" "-I$GUEST_DIR" -include "$GUEST_DIR/sentra_guest_platform.h")
"${CC[@]}" "${CFLAGS[@]}" -c "$UQ/quickjs.c" -o quickjs.o
"${CC[@]}" "${CFLAGS[@]}" -c "$UQ/dtoa.c" -o dtoa.o
"${CC[@]}" "${CFLAGS[@]}" -c "$UQ/libregexp.c" -o libregexp.o
"${CC[@]}" "${CFLAGS[@]}" -c "$UQ/libunicode.c" -o libunicode.o
"${CC[@]}" "${CFLAGS[@]}" -c "$UQ/cutils.c" -o cutils.o
"${CC[@]}" "${CFLAGS[@]}" -c "$GUEST_SRC" -o guest.o
"${CC[@]}" "${CFLAGS[@]}" -c "$GUEST_DIR/sentra_guest_platform.c" -o platform.o

# 3. Link freestanding: no entry, explicit exports, wrapped allocation.
printf '%s\n' sentra_host_call > host-imports.txt
# Driver links static libc/libm. All undefined symbols except our sole ABI
# host import are errors, including accidental WASI/OS dependencies.
# The JS stack allowance is 256 KiB inside a 512 KiB C linear stack. Making
# both exactly 256 KiB underflows QuickJS's stack floor below address zero
# during configure(), causing every evaluation to report stack overflow.
"${CC[@]}" --target=wasm32-wasip1 -nostartfiles -Wl,--no-entry,--export-memory,--stack-first,-z,stack-size=524288 \
  -Wl,--initial-memory=1048576,--max-memory=33554432 \
  -Wl,--export=configure,--export=eval_source,--export=classify_exception \
  -Wl,--export=result_ptr,--export=result_len,--export=error_ptr,--export=error_len \
  -Wl,--export=tool_count,--export=fuel_used,--export=alloc \
  -Wl,--export=reset_heap,--export=shutdown \
  -Wl,--wrap=malloc,--wrap=free,--wrap=realloc,--wrap=calloc,--wrap=malloc_usable_size \
  -Wl,--wrap=__wasi_clock_time_get,--wrap=__wasi_fd_close,--wrap=__wasi_fd_seek,--wrap=__wasi_fd_write \
  -Wl,--allow-undefined-file=host-imports.txt \
  -o sentra_quickjs_guest.wasm \
  quickjs.o dtoa.o libregexp.o libunicode.o cutils.o guest.o platform.o -lm

# 4. Import allowlist: EXACTLY env.sentra_host_call, nothing else (no WASI).
python3 "$GUEST_DIR/inspect_wasm.py" sentra_quickjs_guest.wasm
# 5. The binary ABI reader also checks memory + all twelve function exports,
# exact signatures and absence of a start function; no textual grep inference.

# 6. Hash + CycloneDX SBOM + provenance (all hashes are of built bytes).
WASM_SHA=$(sha256sum sentra_quickjs_guest.wasm | cut -d' ' -f1)
WASM_SIZE=$(stat -c%s sentra_quickjs_guest.wasm)
GUEST_SHA=$(sha256sum "$GUEST_SRC" | cut -d' ' -f1)
python3 - "$WASM_SHA" "$WASM_SIZE" "$GUEST_SHA" "$GUEST_DIR" "$CLANG" "$WASI_SDK" <<'EOF'
import json, sys, pathlib, hashlib
wasm_sha, wasm_size, guest_sha = sys.argv[1], int(sys.argv[2]), sys.argv[3]
source_dir = pathlib.Path(sys.argv[4])
source_manifest = {name: hashlib.sha256((source_dir/name).read_bytes()).hexdigest()
    for name in ('sentra_quickjs_guest.c','sentra_guest_platform.c','sentra_guest_platform.h','ABI.md','inspect_wasm.py','build.sh')}
legal_root = source_dir / 'licenses'
legal = json.loads((legal_root/'PROVENANCE.json').read_text())
if pathlib.Path(sys.argv[6], 'VERSION').read_text().strip() != legal['wasi_sdk']['version']:
    raise SystemExit('WASI SDK differs from static-runtime provenance pin')
for entry in legal['files']:
    path = legal_root/entry['path']
    if path.parent != legal_root or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
        raise SystemExit('static-runtime license pin mismatch')
source_manifest.update({path.relative_to(source_dir).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
    for path in sorted(legal_root.iterdir()) if path.is_file()})
legal_files = [{'path': 'licenses/'+path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    for path in sorted(legal_root.iterdir()) if path.is_file()]
sbom = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1,
  "metadata": {"component": {"type": "application",
    "name": "sentra-quickjs-guest", "version": "1.0.0",
    "hashes": [{"alg": "SHA-256", "content": wasm_sha}],
    "description": "WASI-free QuickJS sandbox for SENTRA Code Mode (A08)"}},
  "components": [
    {"type": "library", "name": "quickjs", "version": "2026-06-04",
     "licenses": [{"license": {"id": "MIT"}}],
     "externalReferences": [{"type": "distribution",
       "url": "https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz",
       "hashes": [{"alg": "SHA-256",
         "content": "b376e839b322978313d929fd20663b11ba58b75df5a46c126dd19ea2fa70ad2a"}]}]},
    {"type": "file", "name": "sentra_quickjs_guest.c",
     "hashes": [{"alg": "SHA-256", "content": guest_sha}],
     "description": "SENTRA ABI v1 guest (ABI.md); sole host import env.sentra_host_call"}]}
sbom['components'].extend({'type':'file','name':name,'hashes':[{'alg':'SHA-256','content':sha}]}
    for name,sha in source_manifest.items() if name != 'sentra_quickjs_guest.c')
sbom['components'].extend([
  {'type':'library','name':'wasi-libc','version':'2e6fb9d8ee0cdf9e431fbcabe8af3115de000a13',
   'licenses':[{'license':{'id':'MIT'}},{'expression':'Apache-2.0 WITH LLVM-exception'}]},
  {'type':'library','name':'llvm-compiler-rt','version':'895aa2c896ada719451be2e3673c83da8ddf1141',
   'licenses':[{'expression':'Apache-2.0 WITH LLVM-exception'}]}])
open("sbom.cdx.json", "w").write(json.dumps(sbom, indent=2))
open("provenance.json", "w").write(json.dumps({
  "guest": "sentra_quickjs_guest.wasm", "wasm_sha256": wasm_sha,
  "wasm_bytes": wasm_size, "sbom": "sbom.cdx.json",
  "upstream": {"url": "https://bellard.org/quickjs/quickjs-2026-06-04.tar.xz",
    "sha256": "b376e839b322978313d929fd20663b11ba58b75df5a46c126dd19ea2fa70ad2a",
    "bytes": 621500, "license": "MIT"},
  "abi": "ABI.md v1", "source_sha256": source_manifest,
  "legal_files": legal_files, "wasi_sdk": legal['wasi_sdk'],
  "upstream_patches": ["disable native CONFIG_ATOMICS", "remove unused dtoa setjmp include"],
  "toolchain": {"target": "wasm32-wasip1", "clang_sha256": hashlib.sha256(pathlib.Path(sys.argv[5]).read_bytes()).hexdigest(),
    "clang_version": pathlib.Path('compiler.txt').read_text()},
  "wasi_imports": [], "host_imports": ["env.sentra_host_call"],
  "validated": False,
  "note": "built bytes; NOT executed — runtime evidence only after final QA liberation"}, indent=2))
EOF

cp sentra_quickjs_guest.wasm sbom.cdx.json provenance.json "$OUT_DIR/"
cp "$UQ/LICENSE" "$OUT_DIR/LICENSE-QuickJS"
cp -R "$GUEST_DIR/licenses" "$OUT_DIR/"
echo "OK: $OUT_DIR/sentra_quickjs_guest.wasm sha256=$WASM_SHA bytes=$WASM_SIZE"
