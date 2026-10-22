"""Workspace-confined project explorer, diff and owner-reviewed editor.

Browsing stays read-only. Writes require a separate Canvas owner approval
and a one-time review ticket bound to the exact file/content revisions.
No agent grant, shell execution or second Electron filesystem authority.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import hashlib
import difflib
import tempfile
from pathlib import Path
from typing import TypedDict


class ProjectEntry(TypedDict):
    name: str
    directory: bool
    path: str

MAX_PREVIEW = 128 * 1024
MAX_LIST = 300
TEXT_EXT = frozenset({".py", ".js", ".jsx", ".ts", ".tsx", ".json", ".md", ".txt",
                      ".css", ".html", ".yml", ".yaml", ".toml", ".c", ".cpp",
                      ".h", ".rs", ".go", ".java", ".sh", ".ps1", ".sql"})
SENSITIVE_NAMES = {".env", ".env.local", ".npmrc", ".pypirc", "id_rsa", "id_ed25519"}


def confined(root: str | Path, relative: str) -> tuple[Path, Path]:
    base = Path(root).resolve(strict=True)
    if not isinstance(relative, str) or len(relative) > 1024 or "\x00" in relative:
        raise ValueError("invalid project path")
    raw = Path(relative)
    if raw.is_absolute() or re.match(r"^[A-Za-z]:", relative):
        raise PermissionError("absolute project paths are not allowed")
    if any(part in ("..", ".git", ".sentra") for part in raw.parts):
        raise PermissionError("protected path outside project browser")
    node = base
    for part in raw.parts:
        node = node / part
        if node.is_symlink() or (hasattr(node, "is_junction") and node.is_junction()):
            raise PermissionError("linked project paths are not available")
    target = node.resolve(strict=True)
    if target != base and not target.is_relative_to(base):
        raise PermissionError("project path escaped workspace")
    return base, target


def list_level(root: str | Path, relative: str = "") -> dict:
    base, folder = confined(root, relative)
    if not folder.is_dir():
        raise ValueError("choose a directory")
    entries: list[ProjectEntry] = []
    with os.scandir(folder) as listing:
        for item in listing:
            if item.name in (".git", ".sentra") or item.name.lower() in SENSITIVE_NAMES:
                continue
            if item.is_symlink() or (hasattr(Path(item.path), "is_junction")
                                    and Path(item.path).is_junction()):
                continue
            if len(entries) >= MAX_LIST:
                raise ValueError("directory has too many entries; narrow your selection")
            if not (item.is_file(follow_symlinks=False) or item.is_dir(follow_symlinks=False)):
                continue
            entries.append({"name": item.name, "directory": item.is_dir(follow_symlinks=False),
                            "path": str(Path(item.path).relative_to(base)).replace("\\", "/")})
    entries.sort(key=lambda x: (not x["directory"], x["name"].casefold()))
    return {"path": relative.replace("\\", "/"), "items": entries, "read_only": True}


def file_preview(root: str | Path, relative: str) -> dict:
    _base, target = confined(root, relative)
    if target.name.lower() in SENSITIVE_NAMES or target.suffix.lower() not in TEXT_EXT:
        raise PermissionError("file type not exposed in read-only preview")
    if not target.is_file():
        raise ValueError("choose a regular text file")
    before = target.stat()
    if before.st_size > MAX_PREVIEW:
        raise ValueError("file exceeds the 128 KiB read-only preview limit")
    with target.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_ino, opened.st_dev, opened.st_size) != (before.st_ino, before.st_dev, before.st_size):
            raise PermissionError("file identity changed before preview")
        content = handle.read(MAX_PREVIEW + 1)
        after = os.fstat(handle.fileno())
    if len(content) > MAX_PREVIEW or (after.st_ino, after.st_dev, after.st_size) != (
            opened.st_ino, opened.st_dev, opened.st_size):
        raise PermissionError("file changed during preview")
    if b"\x00" in content:
        raise ValueError("binary file preview is disabled")
    try:
        content.decode("utf-8", "strict")
        editable=True
    except UnicodeDecodeError:
        editable=False
    return {"path": relative.replace("\\", "/"), "content": content.decode("utf-8", "replace"),
            "read_only": True, "editable":editable,
            "sha256":hashlib.sha256(content).hexdigest(), "size_bytes": len(content)}


def git_diff(root: str | Path, relative: str) -> dict:
    base, target = confined(root, relative)
    if not target.is_file() or target.suffix.lower() not in TEXT_EXT:
        raise ValueError("choose a regular source file for diff")
    git = shutil.which("git")
    if not git:
        raise RuntimeError("git unavailable")
    env = {key: val for key, val in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({"GIT_OPTIONAL_LOCKS": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    relative_path = target.relative_to(base).as_posix()
    result = subprocess.run([git, "-c", "core.fsmonitor=false", "-c", "core.pager=cat",
                             "-c", "diff.external=", "diff", "--no-ext-diff", "--no-textconv",
                             "--", relative_path], cwd=base, env=env, capture_output=True,
                            timeout=5, check=False)
    if result.returncode != 0:
        raise RuntimeError("unable to inspect workspace Git diff")
    if len(result.stdout) > MAX_PREVIEW:
        raise ValueError("diff exceeds the 128 KiB preview limit")
    return {"path": relative_path, "diff": result.stdout.decode("utf-8", "replace"),
            "read_only": True}


def _edit_candidate(root, relative, content, expected_sha256):
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}",expected_sha256):
        raise ValueError("exact original file SHA-256 required")
    if not isinstance(content, str) or "\x00" in content or len(content.encode("utf-8")) > MAX_PREVIEW:
        raise ValueError("editor accepts only bounded UTF-8 text")
    base,target=confined(root,relative)
    if target.name.lower() in SENSITIVE_NAMES or target.suffix.lower() not in TEXT_EXT or not target.is_file():
        raise PermissionError("protected or unsupported project edit target")
    original=file_preview(base,relative)
    if not original["editable"]:
        raise PermissionError("source contains invalid UTF-8 and is not editable")
    if original["sha256"] != expected_sha256:
        raise FileExistsError("file revision changed; reopen before editing")
    new=content.encode("utf-8")
    return base,target,original,new


def preview_edit(root, relative, *, content, expected_sha256):
    """Review exact proposed changes without altering workspace files."""
    _base,_target,original,new=_edit_candidate(root,relative,content,expected_sha256)
    diff="".join(difflib.unified_diff(original["content"].splitlines(keepends=True),
                                    content.splitlines(keepends=True),
                                    fromfile="a/"+original["path"],tofile="b/"+original["path"]))
    if len(diff.encode("utf-8"))>MAX_PREVIEW:
        raise ValueError("edit diff exceeds review budget")
    return {"path":original["path"],"diff":diff,
            "before_sha256":expected_sha256,"after_sha256":hashlib.sha256(new).hexdigest(),
            "changed":original["content"]!=content,"write_performed":False}


def save_edit(root, relative, *, content, expected_sha256, state_root):
    """Owner-only, revision-checked atomic workspace replacement under an OS lock.

    Does not grant an agent filesystem access or execute modified content.
    """
    from sentra_remote.product import _exclusive_registry_lock
    base=Path(root).resolve(strict=True)
    lock_root=Path(state_root).resolve()
    lock_root.mkdir(parents=True,exist_ok=True)
    lock_name=hashlib.sha256((str(base)+"\x00"+relative).encode()).hexdigest()
    with _exclusive_registry_lock(lock_root/("canvas-file-edit-"+lock_name),timeout_s=3):
        base,target,original,new=_edit_candidate(base,relative,content,expected_sha256)
        if original["content"]==content:
            return {"path":original["path"],"sha256":expected_sha256,
                    "written":False,"reason":"unchanged"}
        before=target.stat()
        temp_path=None
        try:
            with tempfile.NamedTemporaryFile(mode="wb",prefix=".sentra-edit-",
                                             suffix=".tmp",dir=target.parent,
                                             delete=False) as handle:
                temp_path=Path(handle.name)
                handle.write(new)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path,before.st_mode)
            # External writers do not necessarily honor SENTRA's lock: verify
            # target revision again immediately before the atomic replacement.
            current=file_preview(base,relative)
            if current["sha256"]!=expected_sha256:
                raise FileExistsError("file changed during review; save refused")
            after=target.stat()
            if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(
                after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns):
                raise FileExistsError("file identity changed during review")
            os.replace(temp_path,target)
            temp_path=None
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return {"path":original["path"],"sha256":hashlib.sha256(new).hexdigest(),
                "previous_sha256":expected_sha256,"written":True,"grants_created":False}


MAX_PDF_BYTES = 4 * 1024 * 1024
MAX_PDF_PAGES = 200
MAX_PDF_TEXT = 32000


def pdf_text_page(root: str | Path, relative: str, *, page: int = 1) -> dict:
    """Bounded read-only page text; not rasterization, OCR or an active PDF viewer."""
    import io
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
    if type(page) is not int or not 1 <= page <= MAX_PDF_PAGES:
        raise ValueError("PDF page must be 1..200")
    _base, target = confined(root, relative)
    if target.suffix.lower() != ".pdf" or not target.is_file():
        raise PermissionError("choose an owned workspace PDF file")
    if target.name.lower() in SENSITIVE_NAMES:
        raise PermissionError("protected PDF not available")
    initial = target.stat()
    if not 0 < initial.st_size <= MAX_PDF_BYTES:
        raise ValueError("PDF exceeds bounded text preview budget")
    with target.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        if (opened.st_ino, opened.st_dev, opened.st_size, opened.st_mtime_ns) != (
            initial.st_ino, initial.st_dev, initial.st_size, initial.st_mtime_ns):
            raise PermissionError("PDF changed before preview")
        payload = handle.read(MAX_PDF_BYTES + 1)
        after = os.fstat(handle.fileno())
    if (len(payload) != opened.st_size or
        (opened.st_ino,opened.st_dev,opened.st_size,opened.st_mtime_ns) !=
        (after.st_ino,after.st_dev,after.st_size,after.st_mtime_ns)):
        raise PermissionError("PDF changed while opening")
    if not payload.startswith(b"%PDF-"):
        raise ValueError("invalid PDF signature")
    try:
        reader = PdfReader(io.BytesIO(payload), strict=True)
        if reader.is_encrypted:
            raise PermissionError("password-protected PDF is not previewed")
        count = len(reader.pages)
        if count > MAX_PDF_PAGES:
            raise ValueError("PDF has too many pages")
        if not count or page > count:
            raise ValueError("PDF page out of range")
        text = reader.pages[page - 1].extract_text() or ""
    except (OSError,TypeError,KeyError,IndexError,RecursionError,PdfReadError) as exc:
        raise ValueError("PDF text preview failed") from exc
    if len(text.encode("utf-8")) > MAX_PDF_TEXT:
        raise ValueError("PDF text page exceeds preview budget")
    return {"path":relative.replace("\\","/"),"page":page,"pages":count,
            "text":text, "text_extracted":bool(text.strip()),
            "source_sha256":hashlib.sha256(payload).hexdigest(),
            "read_only":True,"rendered":False,"ocr_used":False}


# Safe visual PDF projection. No raw PDF/JavaScript reaches the desktop renderer.
# pdfium runs out-of-process with a hard wall clock timeout. It has no workspace
# path: stdin carries only a revision-checked in-memory PDF snapshot.
MAX_PDF_RENDER_PIXELS = 2_500_000
MAX_PDF_RENDER_PNG = 3 * 1024 * 1024
MAX_PDF_RENDER_SECONDS = 5
PDF_RENDER_DPI = frozenset({72, 90, 108})  # Windows DPI: 100%, 125%, 150%
_PDF_WORKER = r"""
import io
import math
import sys
# -I excludes user site; the host passes the explicitly resolved PDFium wheel dir.
sys.path.insert(0, sys.argv[3])
import pypdfium2 as pdfium
from PIL import Image
raw = sys.stdin.buffer.read(4194305)
if not raw.startswith(b'%PDF-') or len(raw) > 4194304:
    raise ValueError('invalid bounded PDF')
page_index = int(sys.argv[1])
dpi = int(sys.argv[2])
document = pdfium.PdfDocument(raw)
if len(document) > 200 or not 0 <= page_index < len(document):
    raise ValueError('page not available')
page = document[page_index]
w, h = page.get_size()
if not math.isfinite(w) or not math.isfinite(h) or w <= 0 or h <= 0:
    raise ValueError('invalid page geometry')
scale = dpi / 72
pixels_w, pixels_h = math.ceil(w * scale), math.ceil(h * scale)
if pixels_w < 1 or pixels_h < 1 or pixels_w * pixels_h > 2500000:
    raise ValueError('page exceeds render geometry budget')
bitmap = page.render(scale=scale, rev_byteorder=True)
picture = bitmap.to_pil().convert('RGB')
output = io.BytesIO()
picture.save(output, format='PNG', optimize=False)
png = output.getvalue()
if len(png) > 3145728:
    raise ValueError('rendered PNG exceeds budget')
sys.stdout.buffer.write(f'{picture.width},{picture.height},{len(document)}\n'.encode('ascii') + png)
"""


def _snapshot_pdf(root: str | Path, relative: str) -> tuple[bytes, str]:
    """Read a confined immutable-by-revision snapshot (no linked/reparse paths)."""
    _base, target = confined(root, relative)
    if target.suffix.lower() != ".pdf" or target.name.lower() in SENSITIVE_NAMES or not target.is_file():
        raise PermissionError("choose a regular workspace PDF")
    before = target.stat()
    if not 0 < before.st_size <= MAX_PDF_BYTES:
        raise ValueError("PDF exceeds the 4 MiB visual preview limit")
    with target.open("rb") as stream:
        start = os.fstat(stream.fileno())
        if (start.st_dev, start.st_ino, start.st_size, start.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ):
            raise PermissionError("PDF changed before reading")
        payload = stream.read(MAX_PDF_BYTES + 1)
        end = os.fstat(stream.fileno())
    if len(payload) != start.st_size or (
        start.st_dev, start.st_ino, start.st_size, start.st_mtime_ns
    ) != (end.st_dev, end.st_ino, end.st_size, end.st_mtime_ns):
        raise PermissionError("PDF changed during reading")
    if not payload.startswith(b"%PDF-"):
        raise ValueError("invalid PDF signature")
    return payload, hashlib.sha256(payload).hexdigest()


def pdf_visual_page(root: str | Path, relative: str, *, page: int = 1, dpi: int = 72) -> dict:
    """Render a page as a *passive* PNG, locally, with bounded memory/geometry/time.

    No OCR, annotations, remote fetch, PDF JavaScript or browser PDF navigation.
    Call only through the Canvas authenticated GET read route (coordinator-owned).
    PDFium is an optional, explicitly installed native dependency; absent => deny.
    """
    import base64
    import importlib.util
    import sys
    if type(page) is not int or not 1 <= page <= MAX_PDF_PAGES:
        raise ValueError("PDF page must be 1..200")
    if type(dpi) is not int or dpi not in PDF_RENDER_DPI:
        raise ValueError("PDF DPI must be one of 72, 90, 108")
    payload, sha = _snapshot_pdf(root, relative)
    # Even PDF document parsing and page enumeration happen in the timed child.
    # The host does not execute pypdf parsing of arbitrary PDF object graphs.
    pdfium_spec = importlib.util.find_spec("pypdfium2")
    if pdfium_spec is None or not pdfium_spec.origin:
        raise RuntimeError("PDFium is not installed; visual PDF preview disabled")
    pdfium_package_root = str(Path(pdfium_spec.origin).resolve().parent.parent)
    # Do not use shell or filesystem paths; native PDF parser is isolated in a
    # bounded child. This is NOT a claim of a kernel-level renderer sandbox.
    try:
        finished = subprocess.run(
            [sys.executable, "-I", "-c", _PDF_WORKER, str(page - 1), str(dpi), pdfium_package_root],
            input=payload, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=MAX_PDF_RENDER_SECONDS, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise TimeoutError("PDF render time budget exceeded") from exc
    if finished.returncode:
        raise RuntimeError("PDF renderer unavailable or page rejected")
    output = finished.stdout
    if len(output) > MAX_PDF_RENDER_PNG + 32 or b"\n" not in output[:32]:
        raise ValueError("PDF render exceeded byte budget")
    header, png = output.split(b"\n", 1)
    import re as _re
    if not _re.fullmatch(rb"[1-9][0-9]{0,4},[1-9][0-9]{0,4},[1-9][0-9]{0,2}", header):
        raise ValueError("invalid PDF renderer dimensions")
    width, height, pages = map(int, header.split(b","))
    if not 0 < pages <= MAX_PDF_PAGES or page > pages or width * height > MAX_PDF_RENDER_PIXELS or len(png) > MAX_PDF_RENDER_PNG or not png.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid PDF renderer output")
    return {
        "path": relative.replace("\\", "/"), "page": page, "pages": pages,
        "dpi": dpi, "width": width, "height": height,
        "image_base64": base64.b64encode(png).decode("ascii"), "mime": "image/png",
        "source_sha256": sha, "read_only": True, "rendered": True,
        "ocr_used": False, "grants_created": False,
    }


def project_revision(root: str | Path, relative: str) -> dict:
    """Workspace-confined SHA probe, no file contents or credentials exposed."""
    if not isinstance(relative, str) or not relative:
        raise ValueError("file path is required")
    _base, target = confined(root, relative)
    if not target.is_file() or target.name.lower() in SENSITIVE_NAMES:
        raise PermissionError("protected or non-file revision target")
    if target.suffix.lower() == ".pdf":
        payload, sha = _snapshot_pdf(root, relative)
        size = len(payload)
    elif target.suffix.lower() in TEXT_EXT:
        preview = file_preview(root, relative)
        sha, size = preview["sha256"], preview["size_bytes"]
    else:
        raise PermissionError("unsupported revision type")
    return {"path": relative.replace("\\", "/"), "sha256": sha,
            "size_bytes": size, "read_only": True, "grants_created": False}


def _win32_file_api():
    """kernel32 entry points for a local file index. Not the process-wide windll."""
    api = getattr(_win32_file_api, "api", None)
    if api is not None:
        return api
    import ctypes
    from ctypes import wintypes

    class _FileTime(ctypes.Structure):
        _fields_ = (("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD))

    class _ByHandleFileInformation(ctypes.Structure):
        _fields_ = (
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", _FileTime),
            ("ftLastAccessTime", _FileTime),
            ("ftLastWriteTime", _FileTime),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
            ("dwVolumeSerialNumber", wintypes.DWORD),
        )

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    kernel.GetDriveTypeW.restype = wintypes.UINT
    kernel.CreateFileW.argtypes = (
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    )
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.GetFileInformationByHandle.argtypes = (
        ctypes.c_void_p, ctypes.POINTER(_ByHandleFileInformation),
    )
    kernel.GetFileInformationByHandle.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel.CloseHandle.restype = wintypes.BOOL
    api = (kernel, _ByHandleFileInformation, ctypes.c_void_p(-1).value)
    _win32_file_api.api = api
    return api


def _network_volume(path: Path) -> bool:
    """True when a handle open would address a UNC or remote drive."""
    if os.name != "nt":
        return False
    text = os.fspath(path).replace("/", "\\")
    if text.upper().startswith("\\\\?\\UNC\\"):
        return True
    if text.startswith("\\\\") and not text.startswith("\\\\?\\"):
        return True
    drive = Path(text).drive
    if not drive:
        return False
    if drive.startswith("\\\\"):
        return True
    root = drive if drive.endswith("\\") else drive + "\\"
    kernel, _information, _invalid = _win32_file_api()
    return kernel.GetDriveTypeW(root) == 4


def _windows_file_index(path: Path) -> tuple[int, int] | None:
    """NT file index via GetFileInformationByHandle, or None when it is absent.

    The handle is opened with FILE_FLAG_OPEN_REPARSE_POINT so a link or junction
    is not followed, and FILE_FLAG_OPEN_NO_RECALL so remote file data is not
    pulled. Desired access is metadata only. A zero index is not an identity.
    """
    if os.name != "nt" or _network_volume(path):
        return None
    import ctypes
    kernel, information, invalid = _win32_file_api()
    # Access 0 + backup semantics reads the index without file bytes.
    handle = kernel.CreateFileW(
        os.fspath(path),
        0,
        0x1 | 0x2 | 0x4,  # FILE_SHARE_READ | WRITE | DELETE
        None,
        3,  # OPEN_EXISTING
        0x00100000 | 0x00200000 | 0x02000000,  # NO_RECALL | OPEN_REPARSE_POINT | BACKUP_SEMANTICS
        None,
    )
    if not handle or handle == invalid:
        return None
    try:
        found = information()
        if not kernel.GetFileInformationByHandle(handle, ctypes.byref(found)):
            return None
        index = (int(found.nFileIndexHigh) << 32) | int(found.nFileIndexLow)
        if index == 0:
            return None
        return (int(found.dwVolumeSerialNumber), index)
    finally:
        kernel.CloseHandle(handle)


def _rename_identity(path: Path, info) -> tuple[int, int] | None:
    """(device, index) that can prove a same-directory rename, or None.

    Zero is never an identity, and file bytes are never hashed to invent one.
    On Windows, DirEntry.stat(follow_symlinks=False) leaves st_ino at 0. os.stat's
    FileId is a different number, so both the stored key and the later scan use
    nFileIndexHigh/Low. If that index is missing, the caller keeps the refusal.
    """
    if os.name == "nt":
        # Enumeration leaves st_ino at 0, which is not an identity. os.stat's
        # non-zero FileId is not nFileIndex, so both observations use the handle.
        return _windows_file_index(path)
    inode = int(getattr(info, "st_ino", 0) or 0)
    if not inode:
        return None
    return (int(info.st_dev), inode)


class ProjectRevisionWatcher:
    """Debounced, per-instance synchronized read-only SHA watcher.

    No threads or background processes are started. Concurrent callers get a
    linearized poll result and closing the watcher invalidates future reads.
    Disappearing, oversized or linked files propagate an error fail-closed:
    last committed revision is never replaced by an unreadable observation.
    """
    def __init__(self, root: str | Path, relative: str, *, debounce_seconds: float = .35):
        import math
        import threading
        if isinstance(debounce_seconds, bool) or not isinstance(debounce_seconds, (int, float)) or (
            not math.isfinite(debounce_seconds) or not 0.05 <= debounce_seconds <= 5
        ):
            raise ValueError("invalid debounce range")
        self.root, self.relative, self.debounce_seconds = root, relative, debounce_seconds
        self.committed = None
        self.pending = None
        self.pending_since = None
        self._last_now: float | None = None
        self._closed = False
        self._watched = False
        self._identity = None
        self._lock = threading.RLock()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self.pending, self.pending_since = None, None

    def _observe(self):
        """Recover a rename in the same bounded directory by file identity.

        Names alone and matching text hashes cannot prove a rename. Never follow
        links, recurse, search other folders or expose protected entries. A
        Windows st_ino of 0 is not an identity; a missing NT file index refuses
        the rename.
        """
        try:
            _base, target = confined(self.root, self.relative)
        except FileNotFoundError:
            if not self._watched:
                raise
            previous = self._identity
            if not previous:
                raise FileNotFoundError("watched file disappeared; rename cannot be established")
            relative = Path(self.relative)
            base, parent = confined(self.root, str(relative.parent) if str(relative.parent) != "." else "")
            candidates = []
            with os.scandir(parent) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_LIST:
                        raise ValueError("rename observation directory exceeds bounded limit")
                    path = Path(entry.path)
                    if (entry.is_symlink() or (hasattr(path, "is_junction") and path.is_junction())
                            or not entry.is_file(follow_symlinks=False)
                            or entry.name.lower() in SENSITIVE_NAMES
                            or path.suffix.lower() not in TEXT_EXT | {".pdf"}):
                        continue
                    info = entry.stat(follow_symlinks=False)
                    if _rename_identity(path, info) == previous:
                        candidates.append(path.relative_to(base).as_posix())
            if len(candidates) != 1:
                raise FileNotFoundError("watched file disappeared; rename cannot be established")
            old = self.relative
            candidate = candidates[0]
            revision = project_revision(self.root, candidate)
            # A rejected read must not retarget the watcher. The directory
            # entry can also be replaced during that read, so recheck the
            # physical identity before accepting its new path.
            _base, observed = confined(self.root, candidate)
            if _rename_identity(observed, observed.stat(follow_symlinks=False)) != previous:
                raise FileNotFoundError("watched file identity changed during rename observation")
            self.relative = candidate
            return revision, old
        info = target.stat(follow_symlinks=False)
        self._watched = True
        self._identity = _rename_identity(target, info)
        return project_revision(self.root, self.relative), None

    def poll(self, *, now: float | None = None) -> dict:
        import math
        import time
        moment = time.monotonic() if now is None else now
        if isinstance(moment, bool) or not isinstance(moment, (float, int)) or not math.isfinite(moment):
            raise ValueError("invalid watcher clock")
        with self._lock:
            if self._closed:
                raise RuntimeError("watcher has been closed")
            if self._last_now is not None and moment < self._last_now:
                raise ValueError("watcher clock cannot run backward")
            # The read is *inside* this lock to serialize simultaneous polls.
            # A reader never commits a SHA from another in-flight observation.
            revision, renamed_from = self._observe()
            if renamed_from:
                # Debounce the revised bytes independently after a rename. The
                # notification itself never grants permission to write a path.
                self.pending, self.pending_since = None, None
                self._last_now = moment
                return {**revision, "state": "renamed", "previous_path": renamed_from}
            self._last_now = moment
            sha = revision["sha256"]
            if self.committed is None:
                self.committed = sha
                return {**revision, "state": "initial"}
            if sha == self.committed:
                self.pending, self.pending_since = None, None
                return {**revision, "state": "unchanged"}
            if sha != self.pending:
                self.pending, self.pending_since = sha, moment
                return {**revision, "state": "pending"}
            if moment - self.pending_since < self.debounce_seconds:
                return {**revision, "state": "pending"}
            self.committed = sha
            self.pending, self.pending_since = None, None
            return {**revision, "state": "changed"}


class ProjectWatchRegistry:
    """Owner-HTTP read projection with bounded, expiring watcher handles.

    The Canvas composition supplies project_id/root from its trusted workspace.
    A handle cannot cross projects. No filesystem notification starts effects.
    """
    def __init__(self, *, max_watchers=128, ttl_seconds=300, clock=None):
        import threading
        import time
        if type(max_watchers) is not int or not 1 <= max_watchers <= 512:
            raise ValueError("invalid watcher quota")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 900:
            raise ValueError("invalid watcher lifetime")
        self.clock = clock or time.monotonic
        self.max_watchers, self.ttl_seconds = max_watchers, ttl_seconds
        self._lock, self._watchers = threading.RLock(), {}

    def _expire(self):
        for handle, (_, watcher, until) in list(self._watchers.items()):
            if until <= self.clock():
                watcher.close()
                del self._watchers[handle]

    def start(self, project_id, root, relative, *, debounce_seconds=.35):
        import secrets
        from sentra_collab.authority import _id
        _id(project_id)
        watcher = ProjectRevisionWatcher(root, relative, debounce_seconds=debounce_seconds)
        with self._lock:
            self._expire()
            if len(self._watchers) >= self.max_watchers:
                raise ValueError("project watcher quota reached")
            initial = watcher.poll()
            handle = "watch-" + secrets.token_hex(16)
            self._watchers[handle] = (project_id, watcher, self.clock() + self.ttl_seconds)
            return {**initial, "watch_id": handle, "project_id": project_id}

    def poll(self, project_id, watch_id):
        with self._lock:
            self._expire()
            row = self._watchers.get(watch_id)
            if not row or row[0] != project_id:
                raise PermissionError("watcher is expired or belongs to another project")
            result = row[1].poll()
            self._watchers[watch_id] = (project_id, row[1], self.clock() + self.ttl_seconds)
            return {**result, "watch_id": watch_id, "project_id": project_id}

    def close(self, project_id, watch_id):
        with self._lock:
            row = self._watchers.get(watch_id)
            if row and row[0] != project_id:
                raise PermissionError("watcher belongs to another project")
            if row:
                row[1].close()
                del self._watchers[watch_id]
            return {"closed": True, "watch_id": watch_id, "project_id": project_id}


PROJECT_REVIEW_ACTIONS = frozenset({"project_file_list", "project_file_preview", "project_file_diff",
    "project_file_pdf_text", "project_file_pdf_visual", "project_watch_start", "project_watch_poll", "project_watch_close"})


class ProjectReviewService:
    """Read-only shell adapter. Root resolver belongs to Canvas authority."""
    def __init__(self, resolve_root):
        if not callable(resolve_root):
            raise ValueError("trusted project root resolver required")
        self.resolve_root = resolve_root
        self.watchers = ProjectWatchRegistry()

    def dispatch(self, action, payload, *, project_id):
        from sentra_collab.authority import _id
        _id(project_id)
        if action not in PROJECT_REVIEW_ACTIONS or not isinstance(payload, dict):
            raise ValueError("unsupported project read action")
        if set(payload) & {"root", "owner", "principal_id", "grant", "content"}:
            raise PermissionError("project preview cannot supply filesystem authority")
        root = self.resolve_root(project_id)
        relative = payload.get("path", "")
        if action == "project_file_list":
            return list_level(root, relative)
        if action == "project_file_preview":
            return file_preview(root, relative)
        if action == "project_file_diff":
            return git_diff(root, relative)
        if action == "project_file_pdf_text":
            return pdf_text_page(root, relative, page=payload.get("page", 1))
        if action == "project_file_pdf_visual":
            return pdf_visual_page(root, relative, page=payload.get("page", 1), dpi=payload.get("dpi", 72))
        if action == "project_watch_start":
            return self.watchers.start(project_id, root, relative)
        watch_id = _id(payload.get("watch_id"))
        if action == "project_watch_poll":
            return self.watchers.poll(project_id, watch_id)
        return self.watchers.close(project_id, watch_id)
