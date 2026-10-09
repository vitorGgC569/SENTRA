"""Scoped RPA primitives, atomic artifacts and optional owned document workers."""
from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import os
import tempfile
import threading
import json
import subprocess
import signal
import sys
import time
import queue
from dataclasses import dataclass
from pathlib import Path

from ._base import GuardedExecutor


class OwnedProcessHandle:
    """Retain a kernel process handle, never kill a later reused PID."""
    def __init__(self, pid):
        self.pid, self.handle, self._closed = pid, None, False
        if os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
            kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
            self._kernel = kernel
            self.handle = kernel.OpenProcess(0x0001 | 0x00100000 | 0x1000, False, pid)
            if not self.handle: raise ExecutorFailure('owned_process_handle_unavailable')
        elif hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
            self.handle = os.pidfd_open(pid)
        else:
            raise ExecutorFailure('owned_process_handle_unsupported_platform')

    def terminate(self):
        if self._closed: return
        if os.name == 'nt':
            self._kernel.TerminateProcess(self.handle, 1)
        else:
            signal.pidfd_send_signal(self.handle, signal.SIGKILL)

    def close(self):
        if self._closed: return
        self._closed = True
        if os.name == 'nt': self._kernel.CloseHandle(self.handle)
        else: os.close(self.handle)


class _WindowsJob:
    """Worker waits for stdin until assigned; all its children inherit this job."""
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        class Basic(ctypes.Structure):
            _fields_ = [('process_time', ctypes.c_int64), ('job_time', ctypes.c_int64),
                ('flags', wintypes.DWORD), ('min_working', ctypes.c_size_t), ('max_working', ctypes.c_size_t),
                ('active', wintypes.DWORD), ('affinity', ctypes.c_size_t),
                ('priority', wintypes.DWORD), ('scheduling', wintypes.DWORD)]
        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(ctypes.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_mem', ctypes.c_size_t),
                ('job_mem', ctypes.c_size_t), ('peak_process', ctypes.c_size_t), ('peak_job', ctypes.c_size_t)]
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        self.kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        self.kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        self.handle = self.kernel.CreateJobObjectW(None, None)
        limits = Extended(); limits.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.handle or not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close(); raise ExecutorFailure('owned_process_job_unavailable')

    def assign(self, process_handle):
        if not self.kernel.AssignProcessToJobObject(self.handle, process_handle):
            raise ExecutorFailure('owned_process_job_assignment_failed')

    def close(self):
        if getattr(self, 'handle', None):
            self.kernel.CloseHandle(self.handle); self.handle = None


def run_owned_worker(python_executable, script, config, *, timeout_seconds):
    """Fixed worker, bounded result channel, isolated process tree and deadline.

    No stdout logging of secrets. Before workbook I/O an Excel worker announces
    its new COM server PID and waits for a parent ACK. Existing PIDs are refused.
    """
    executable = Path(python_executable)
    if not executable.is_absolute() or not executable.is_file():
        raise ExecutorFailure('configured_python_missing')
    excel_baseline = set()
    if config.get('kind') == 'excel':
        dependency('psutil', (5, 9))
        import psutil
        excel_baseline = {p.pid for p in psutil.process_iter(['name']) if (p.info['name'] or '').lower() == 'excel.exe'}
    job = _WindowsJob() if os.name == 'nt' else None
    process = None
    owned_excel = None
    excel_starting = False
    messages = queue.Queue(maxsize=16)
    overflow = threading.Event()
    try:
        effect_checkpoint()
        process = subprocess.Popen([str(executable), '-c', script], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
            start_new_session=os.name != 'nt',
            creationflags=0x08000000 if os.name == 'nt' else 0)
        if job: job.assign(process._handle)
        def read_results():
            try:
                while True:
                    line = process.stdout.readline(65537)
                    if not line: return
                    if len(line) > 65536 or not line.endswith('\n'):
                        overflow.set(); return
                    try: messages.put_nowait(json.loads(line))
                    except (ValueError, queue.Full): overflow.set(); return
            finally:
                try: messages.put_nowait({'event': 'eof'})
                except queue.Full: pass
        reader = threading.Thread(target=read_results, daemon=True, name='sentra-owned-worker-output')
        reader.start()
        deadline = time.monotonic() + timeout_seconds
        process.stdin.write(json.dumps(config, allow_nan=False)+'\n'); process.stdin.flush()
        while True:
            if time.monotonic() >= deadline:
                raise ExecutorFailure('excel_creation_timeout_ownership_unknown' if excel_starting and owned_excel is None
                    else 'document_provider_timeout', uncertain=excel_starting and owned_excel is None,
                    evidence={'owned_worker_pid': process.pid})
            if overflow.is_set(): raise ExecutorFailure('document_provider_output_limit')
            effect_checkpoint()
            try: message = messages.get(timeout=min(0.2, max(0.001, deadline-time.monotonic())))
            except queue.Empty: continue
            if message.get('event') == 'checkpoint':
                if message.get('phase') not in {'excel_create','open','calculate','save','office_start','render','ocr'}:
                    raise ExecutorFailure('unknown_document_worker_phase')
                effect_checkpoint()
                if message['phase']=='excel_create': excel_starting=True
                process.stdin.write('CONTINUE\n'); process.stdin.flush()
            elif message.get('event') == 'excel_created':
                pid = message.get('pid')
                if type(pid) is not int or pid in excel_baseline or owned_excel is not None:
                    raise ExecutorFailure('excel_process_ownership_unproven')
                # The retained handle guards against PID reuse. Never attach or
                # terminate an Excel instance that existed before this worker.
                owned_excel = OwnedProcessHandle(pid)
                if job: job.assign(owned_excel.handle)
                effect_checkpoint()
                process.stdin.write('OWNED\n'); process.stdin.flush()
            elif message.get('event') == 'result':
                if message.get('ok') is not True:
                    raise ExecutorFailure(message.get('code', 'document_provider_failed'))
                process.wait(timeout=max(0.001, deadline-time.monotonic()))
                if process.returncode != 0: raise ExecutorFailure('document_worker_failed')
                return message['evidence']
            elif message.get('event') == 'eof':
                raise ExecutorFailure('document_worker_exited_without_result')
    except ExecutorFailure as exc:
        if excel_starting and owned_excel is None:
            raise ExecutorFailure(exc.code,uncertain=True,evidence=dict(exc.evidence,
                excel_creation_ownership_unknown=True)) from exc
        raise
    finally:
        if owned_excel:
            if process is not None and process.poll() is None: owned_excel.terminate()
            owned_excel.close()
        if job: job.close()
        elif process is not None:
            # A new session/process group is created solely for this worker;
            # keep its leader unreaped until group termination to avoid reuse.
            if process.poll() is None:
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
        if process is not None:
            if process.poll() is None: process.kill()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: pass
            for pipe in (process.stdin, process.stdout):
                if pipe: pipe.close()


class ExecutorFailure(RuntimeError):
    def __init__(self, code: str, *, uncertain: bool = False, evidence=None):
        super().__init__(code)
        self.code, self.uncertain, self.evidence = code, uncertain, evidence or {}


def dependency(name: str, minimum: tuple[int, ...]):
    """Import the actual provider, never a fixture or automatic installer."""
    try:
        version = importlib.metadata.version(name)
        parts = tuple(int(p) for p in version.split('.')[:len(minimum)])
        if parts < minimum:
            raise ExecutorFailure(f"unsupported_{name}_version", evidence={
                "installed": version, "minimum": '.'.join(map(str, minimum))})
        return importlib.import_module(name)
    except (ImportError, importlib.metadata.PackageNotFoundError) as exc:
        raise ExecutorFailure(f"dependency_missing_{name}", evidence={
            "required": name, "minimum": '.'.join(map(str, minimum))}) from exc
    except ValueError as exc:
        raise ExecutorFailure(f"unsupported_{name}_version") from exc


def dependency_versions() -> dict:
    result = {}
    for name in ("playwright", "openpyxl", "pypdf"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def effect_checkpoint() -> None:
    """Recheck the host's existing effect authority before compound effects."""
    try:
        from sentra_runtime.effect_boundary import current_effect_context
    except ImportError:
        return  # Standalone registry still requires its explicit policy callback.
    context = current_effect_context.get()
    if context is not None:
        try:
            context.checkpoint()
        except Exception as exc:
            raise ExecutorFailure('effect_checkpoint_denied') from exc


@dataclass(frozen=True)
class AuthorizedPaths:
    read_roots: tuple[str, ...]
    write_roots: tuple[str, ...] = ()
    excluded_roots: tuple[str, ...] = ()

    def __post_init__(self):
        for root in self.read_roots + self.write_roots + self.excluded_roots:
            if not isinstance(root, str) or not Path(root).is_absolute():
                raise ValueError("absolute_authorized_roots_required")
            if not Path(root).is_dir():
                raise ValueError("authorized_root_must_exist")
        # Resolve once: later symlink/junction substitutions cannot enlarge scope.
        object.__setattr__(self, "read_roots", tuple(str(Path(p).resolve()) for p in self.read_roots))
        object.__setattr__(self, "write_roots", tuple(str(Path(p).resolve()) for p in self.write_roots))
        object.__setattr__(self, "excluded_roots", tuple(str(Path(p).resolve()) for p in self.excluded_roots))

    def resolve(self, value: str, *, write: bool = False) -> Path:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError("absolute_path_required")
        # Block Windows ADS/device paths; UNC is permitted only via an explicit root.
        if ':' in value.replace('\\', '/')[2:] or value.startswith(('\\\\?\\', '\\\\.\\')):
            raise ValueError("device_or_stream_path_denied")
        path = Path(value).resolve(strict=not write)
        if any(path.is_relative_to(Path(root)) for root in self.excluded_roots):
            raise ValueError("path_inside_protected_host_storage")
        roots = self.write_roots if write else self.read_roots
        if not any(path.is_relative_to(Path(root)) for root in roots):
            raise ValueError("path_outside_authorized_roots")
        if write:
            if not path.parent.is_dir() or path.is_dir():
                raise ValueError("output_parent_required")
        elif not path.is_file():
            raise ValueError("input_file_required")
        return path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


class OutputPathLock:
    """OS file lock shared by all agents/processes publishing this resolved path.

    Lock files intentionally persist; unlinking them can split lock ownership.
    Workspaces must keep this small lock directory under host ownership.
    """
    def __init__(self, target: Path, *, timeout_seconds=10):
        self.target, self.timeout_seconds, self.stream = target, timeout_seconds, None

    def __enter__(self):
        effect_checkpoint()
        directory = self.target.parent / '.sentra-output-locks'
        directory.mkdir(exist_ok=True)
        if directory.resolve().parent != self.target.parent:
            raise ExecutorFailure('output_lock_scope_changed')
        key = hashlib.sha256(os.path.normcase(str(self.target)).encode('utf-8')).hexdigest()
        lock_path = directory / (key + '.lock')
        if lock_path.is_symlink(): raise ExecutorFailure('output_lock_symlink_denied')
        self.stream = lock_path.open('a+b')
        if self.stream.seek(0, os.SEEK_END) == 0:
            self.stream.write(b'0'); self.stream.flush()
        deadline = time.monotonic()+self.timeout_seconds
        while True:
            try:
                effect_checkpoint()
                if os.name == 'nt':
                    import msvcrt
                    self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except ExecutorFailure:
                self.stream.close(); raise
            except OSError as exc:
                if exc.errno not in (11, 13, 35, 36):
                    self.stream.close(); raise ExecutorFailure('output_lock_unavailable') from exc
                if time.monotonic() >= deadline:
                    self.stream.close(); raise ExecutorFailure('output_path_busy') from exc
                time.sleep(0.02)

    def __exit__(self, *_):
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0); msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass  # Closing the retained descriptor releases the OS lock too.
        finally:
            self.stream.close()


def atomic_output(paths: AuthorizedPaths, output: str, producer, verifier, *, overwrite=False,
                  max_output_bytes=128 * 1024 * 1024, lock_timeout_seconds=10) -> dict:
    if (type(max_output_bytes) is not int or not 1<=max_output_bytes<=512*1024*1024 or
            not 0<lock_timeout_seconds<=30 or type(overwrite) is not bool):
        raise ExecutorFailure('invalid_atomic_output_bounds')
    target = paths.resolve(output, write=True)
    with OutputPathLock(target, timeout_seconds=lock_timeout_seconds):
        return _atomic_output_locked(paths, output, producer, verifier, overwrite=overwrite,
                                     max_output_bytes=max_output_bytes)


def _atomic_output_locked(paths, output, producer, verifier, *, overwrite, max_output_bytes):
    """Verify temporary bytes before publication; no partial destination on failure.

    No-overwrite publication uses an atomic hard link, not a check-then-rename.
    Unsupported filesystems fail closed. Explicit overwrite uses os.replace.
    """
    target = paths.resolve(output, write=True)
    if target.exists() and not overwrite:
        raise ExecutorFailure("output_exists")
    effect_checkpoint()
    fd, temporary = tempfile.mkstemp(prefix='.sentra-', suffix=target.suffix, dir=target.parent)
    os.close(fd)
    temp = Path(temporary)
    try:
        producer(temp)
        if temp.stat().st_size > max_output_bytes:
            raise ExecutorFailure('output_size_limit')
        verifier(temp)
        # Windows FlushFileBuffers requires a writable handle.
        with temp.open('r+b') as stream:
            os.fsync(stream.fileno())
        sha, size = digest(temp), temp.stat().st_size
        if paths.resolve(output, write=True) != target:
            raise ExecutorFailure("output_scope_changed")
        effect_checkpoint()
        if overwrite:
            try:
                os.replace(temp, target)
            except OSError as exc:
                raise ExecutorFailure('atomic_replace_failed') from exc
        else:
            try:
                os.link(temp, target)
            except FileExistsError as exc:
                raise ExecutorFailure("output_exists") from exc
            except OSError as exc:
                raise ExecutorFailure('atomic_publish_unavailable') from exc
        artifact = {"path": str(target), "sha256": sha, "bytes": size,
                    "verified_before_publish": True, "publication_locked": True}
        # Snapshot bytes under the SAME per-path lock, before another agent
        # can replace the workspace output. Standalone tests need no authority.
        try:
            try:
                from sentra_runtime.effect_boundary import current_effect_context
                context = current_effect_context.get()
            except ImportError:
                context = None
            if context is not None:
                capture = getattr(context, 'capture_output', None)
                if not callable(capture): raise RuntimeError('capture_output unavailable')
                durable = capture(target, expected_sha256=sha, max_bytes=max_output_bytes)
                if not isinstance(durable, dict) or not durable.get('artifact_id') or not durable.get('resource_uri'):
                    raise RuntimeError('durable artifact identity missing')
                artifact.update(artifact_id=durable['artifact_id'], resource_uri=durable['resource_uri'],
                                durable_capture=True)
        except Exception as exc:
            raise ExecutorFailure('output_published_capture_failed', uncertain=True,
                                  evidence={'artifact': artifact}) from exc
        return artifact
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            # Promotion may already have happened. Never relabel it as failed.
            pass


class DiagnosedExecutor(GuardedExecutor):
    """Keep the current gate/idempotency contract, expose bounded provider errors."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._diagnoses = {}
        self._diagnosis_lock = threading.Lock()

    def _check_request(self, request):
        try:
            binding, args = super()._check_request(request)
            # OperationRequest is frozen, but nested caller dictionaries are not.
            return binding, json.loads(json.dumps(args, allow_nan=False))
        except OSError as exc:
            raise ValueError('invalid_file_scope') from exc

    def _execute(self, binding, arguments):
        try:
            return self._run(binding, arguments)
        except ExecutorFailure as exc:
            with self._diagnosis_lock:
                self._diagnoses[arguments['_operation_id']] = exc
            raise

    async def start(self, request):
        result = await super().start(request)
        if result.error == 'backend_error':
            with self._diagnosis_lock:
                failure = self._diagnoses.get(request.operation_id)
            if failure:
                return await self._finish(request.operation_id,
                    'uncertain' if failure.uncertain else 'failed',
                    error=failure.code, evidence=failure.evidence)
        return result


# Standalone trusted worker: configured Python may be LibreOffice's UNO Python
# and need not import SENTRA or its central services. stdin gates startup until
# the parent has placed the worker in its owned process job/group.
DOCUMENT_WORKER_SCRIPT = r'''
import sys, json, time, subprocess, pathlib, tempfile, math, os
cfg=json.loads(sys.stdin.readline())
deadline=time.monotonic()+cfg['timeout']
app=book=office=None
owned_excel=False
def remaining():
    value=deadline-time.monotonic()
    if value<=0: raise TimeoutError()
    return value
def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)
def checkpoint(phase):
    remaining(); emit({'event':'checkpoint','phase':phase})
    if sys.stdin.readline().strip()!='CONTINUE': raise RuntimeError('document_worker_checkpoint_denied')
def prop(uno, name, value):
    p=uno.createUnoStruct('com.sun.star.beans.PropertyValue'); p.Name=name; p.Value=value; return p
try:
    if cfg['kind']=='excel':
        if os.name!='nt': raise RuntimeError('excel_requires_windows')
        try:
            import pythoncom, win32com.client, win32process
        except ImportError: raise RuntimeError('dependency_missing_pywin32')
        pythoncom.CoInitialize()
        checkpoint('excel_create'); app=win32com.client.DispatchEx('Excel.Application')
        _,pid=win32process.GetWindowThreadProcessId(app.Hwnd)
        emit({'event':'excel_created','pid':pid})
        if sys.stdin.readline().strip()!='OWNED': raise RuntimeError('excel_ownership_ack_missing')
        owned_excel=True
        app.Visible=False; app.DisplayAlerts=False; app.EnableEvents=False
        app.AutomationSecurity=3
        checkpoint('open'); book=app.Workbooks.Open(cfg['input'], UpdateLinks=0, ReadOnly=False,
            IgnoreReadOnlyRecommended=True, AddToMru=False, Notify=False)
        checkpoint('calculate'); app.CalculateFullRebuild()
        while app.CalculationState!=0:
            remaining(); pythoncom.PumpWaitingMessages(); time.sleep(0.02)
        checkpoint('save'); book.SaveAs(cfg['output'], FileFormat=51)
        evidence={'provider':'excel','version':str(app.Version),'calculation_complete':True,'pid':pid}
    elif cfg['kind']=='libreoffice':
        try: import uno
        except ImportError: raise RuntimeError('dependency_missing_pyuno')
        profile=pathlib.Path(cfg['workdir'])/'profile'; profile.mkdir()
        pipe='sentra_'+cfg['token']
        checkpoint('office_start'); office=subprocess.Popen([cfg['executable'],'--headless','--nologo','--nodefault','--norestore',
            '-env:UserInstallation='+profile.as_uri(), '--accept=pipe,name='+pipe+';urp;StarOffice.ServiceManager'],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        local=uno.getComponentContext()
        resolver=local.ServiceManager.createInstanceWithContext('com.sun.star.bridge.UnoUrlResolver',local)
        context=None
        while context is None:
            remaining()
            if office.poll() is not None: raise RuntimeError('libreoffice_startup_failed')
            try: context=resolver.resolve('uno:pipe,name='+pipe+';urp;StarOffice.ComponentContext')
            except Exception: time.sleep(0.05)
        desktop=context.ServiceManager.createInstanceWithContext('com.sun.star.frame.Desktop',context)
        options=(prop(uno,'Hidden',True),prop(uno,'ReadOnly',False),
            prop(uno,'MacroExecutionMode',uno.getConstantByName('com.sun.star.document.MacroExecMode.NEVER_EXECUTE')),
            prop(uno,'UpdateDocMode',uno.getConstantByName('com.sun.star.document.UpdateDocMode.NO_UPDATE')))
        checkpoint('open'); book=desktop.loadComponentFromURL(pathlib.Path(cfg['input']).as_uri(),'_blank',0,options)
        if book is None or not book.supportsService('com.sun.star.sheet.SpreadsheetDocument'):
            raise RuntimeError('libreoffice_not_a_spreadsheet')
        checkpoint('calculate'); book.calculateAll(); remaining()
        checkpoint('save')
        book.storeAsURL(pathlib.Path(cfg['output']).as_uri(),(
            prop(uno,'FilterName','Calc MS Excel 2007 XML'),prop(uno,'Overwrite',True)))
        evidence={'provider':'libreoffice','calculation_complete':True,'isolated_profile':True,'pid':office.pid}
    elif cfg['kind']=='ocr':
        try: import pymupdf
        except ImportError: raise RuntimeError('dependency_missing_pymupdf')
        import importlib.metadata
        if tuple(int(v) for v in importlib.metadata.version('pymupdf').split('.')[:2])<(1,24):
            raise RuntimeError('unsupported_pymupdf_version')
        result=[]; total=0
        with pymupdf.open(cfg['input']) as pdf:
            if pdf.needs_pass: raise RuntimeError('encrypted_pdf_unsupported')
            for number in cfg['pages']:
                checkpoint('render')
                page=pdf[number-1]; scale=cfg['dpi']/72
                width,height=math.ceil(page.rect.width*scale),math.ceil(page.rect.height*scale)
                if width*height>cfg['max_pixels']: raise RuntimeError('ocr_pixel_limit')
                image=pathlib.Path(cfg['workdir'])/('page-'+str(number)+'.png')
                page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),colorspace=pymupdf.csRGB,alpha=False).save(image)
                base=pathlib.Path(cfg['workdir'])/('text-'+str(number))
                checkpoint('ocr'); child=subprocess.Popen([cfg['executable'],str(image),str(base),'-l',cfg['language'],'--dpi',str(cfg['dpi'])],
                    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                try: child.wait(timeout=remaining())
                except subprocess.TimeoutExpired: child.kill(); child.wait(); raise TimeoutError()
                if child.returncode!=0: raise RuntimeError('tesseract_failed')
                text_path=base.with_suffix('.txt')
                if text_path.stat().st_size+total>cfg['max_text_bytes']: raise RuntimeError('ocr_text_limit')
                text=text_path.read_text(encoding='utf-8'); total+=text_path.stat().st_size
                result.append({'page':number,'text':text}); image.unlink(); text_path.unlink()
        pathlib.Path(cfg['output']).write_text(json.dumps({'pages':result,'ocr_performed':True,
            'language':cfg['language'],'dpi':cfg['dpi']}),encoding='utf-8')
        evidence={'provider':'tesseract+pymupdf','ocr_performed':True,'rendered_pages':len(result)}
    else: raise RuntimeError('unsupported_document_provider')
    remaining()
    if cfg['kind']=='excel': book.Close(SaveChanges=False); book=None; app.Quit(); app=None
    if cfg['kind']=='libreoffice':
        book.close(True); book=None; desktop.terminate(); office.wait(timeout=remaining())
    emit({'event':'result','ok':True,'evidence':evidence})
except Exception as exc:
    code=str(exc) if isinstance(exc,RuntimeError) and str(exc).replace('_','').isalnum() else (
        'document_provider_timeout' if isinstance(exc,(TimeoutError,subprocess.TimeoutExpired)) else 'document_provider_failed')
    emit({'event':'result','ok':False,'code':code})
finally:
    if cfg['kind']=='excel' and owned_excel:
        try:
            if book is not None: book.Close(SaveChanges=False)
            if app is not None: app.Quit()
        except Exception: pass
    if cfg['kind']=='libreoffice':
        try:
            if book is not None: book.close(True)
        except Exception: pass
        if office is not None and office.poll() is None:
            office.terminate()
            try: office.wait(timeout=2)
            except Exception: office.kill()
'''
