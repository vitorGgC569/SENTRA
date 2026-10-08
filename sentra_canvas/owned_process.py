"""OS-owned process trees. Windows children join a kill-on-close Job before run."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import signal
import subprocess
import threading


class _BasicLimits(ctypes.Structure):
    _fields_=[("process_time",ctypes.c_longlong),("job_time",ctypes.c_longlong),
              ("flags",wintypes.DWORD),("min_ws",ctypes.c_size_t),("max_ws",ctypes.c_size_t),
              ("active_limit",wintypes.DWORD),("affinity",ctypes.c_size_t),
              ("priority",wintypes.DWORD),("scheduling",wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_=[("basic",_BasicLimits),("io",ctypes.c_ulonglong*6),
              ("process_memory",ctypes.c_size_t),("job_memory",ctypes.c_size_t),
              ("peak_process_memory",ctypes.c_size_t),("peak_job_memory",ctypes.c_size_t)]


class _ThreadEntry(ctypes.Structure):
    _fields_=[("size",wintypes.DWORD),("usage",wintypes.DWORD),("id",wintypes.DWORD),
              ("pid",wintypes.DWORD),("base",wintypes.LONG),("delta",wintypes.LONG),
              ("flags",wintypes.DWORD)]


class WindowsJob:
    def __init__(self):
        if os.name!="nt":raise RuntimeError("Windows Job requires Windows")
        self.lock=threading.RLock()
        self.kernel=ctypes.WinDLL("kernel32",use_last_error=True)
        k=self.kernel;H=wintypes.HANDLE
        k.CreateJobObjectW.argtypes=[ctypes.c_void_p,wintypes.LPCWSTR];k.CreateJobObjectW.restype=H
        k.SetInformationJobObject.argtypes=[H,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD]
        k.SetInformationJobObject.restype=wintypes.BOOL
        k.AssignProcessToJobObject.argtypes=[H,H];k.AssignProcessToJobObject.restype=wintypes.BOOL
        k.TerminateJobObject.argtypes=[H,wintypes.UINT];k.TerminateJobObject.restype=wintypes.BOOL
        k.CloseHandle.argtypes=[H];k.CloseHandle.restype=wintypes.BOOL
        self.handle=k.CreateJobObjectW(None,None)
        if not self.handle:raise ctypes.WinError(ctypes.get_last_error())
        limits=_ExtendedLimits();limits.basic.flags=0x00002000 # KILL_ON_JOB_CLOSE; no breakaway
        if not k.SetInformationJobObject(self.handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            error=ctypes.get_last_error();self.close();raise ctypes.WinError(error)

    def assign(self,process_handle):
        if not self.kernel.AssignProcessToJobObject(self.handle,process_handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def assign_suspended_pid(self,pid):
        """Popen closes its initial thread handle; find only this suspended child."""
        k=self.kernel;H=wintypes.HANDLE
        k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenProcess.restype=H
        k.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD];k.CreateToolhelp32Snapshot.restype=H
        for name in ("Thread32First","Thread32Next"):
            fn=getattr(k,name);fn.argtypes=[H,ctypes.POINTER(_ThreadEntry)];fn.restype=wintypes.BOOL
        k.OpenThread.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];k.OpenThread.restype=H
        k.ResumeThread.argtypes=[H];k.ResumeThread.restype=wintypes.DWORD
        process=k.OpenProcess(0x0101,False,pid) # SET_QUOTA | TERMINATE
        if not process:raise ctypes.WinError(ctypes.get_last_error())
        try:self.assign(process)
        finally:k.CloseHandle(process)
        snapshot=k.CreateToolhelp32Snapshot(4,0) # TH32CS_SNAPTHREAD
        if snapshot==ctypes.c_void_p(-1).value:raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry=_ThreadEntry();entry.size=ctypes.sizeof(entry)
            ids=[];more=k.Thread32First(snapshot,ctypes.byref(entry))
            while more:
                if entry.pid==pid:ids.append(entry.id)
                entry.size=ctypes.sizeof(entry)
                more=k.Thread32Next(snapshot,ctypes.byref(entry))
            if len(ids)!=1:raise RuntimeError("suspended child thread identity is ambiguous")
            thread=k.OpenThread(2,False,ids[0])
            if not thread:raise ctypes.WinError(ctypes.get_last_error())
            try:
                if k.ResumeThread(thread)!=1:
                    raise RuntimeError("child could not be resumed from its initial suspended state")
            finally:k.CloseHandle(thread)
        finally:k.CloseHandle(snapshot)

    def terminate(self):
        with self.lock:
            if self.handle and not self.kernel.TerminateJobObject(self.handle,1):
                raise ctypes.WinError(ctypes.get_last_error())

    def close(self):
        with self.lock:
            if self.handle:
                self.kernel.CloseHandle(self.handle);self.handle=None


class TaskProcess:
    def __init__(self,command,**options):
        self.job=WindowsJob() if os.name=="nt" else None
        self.process=None
        try:
            if self.job:
                options["creationflags"]=options.get("creationflags",0)|0x00000004 # CREATE_SUSPENDED
            else:options["start_new_session"]=True
            self.process=subprocess.Popen(command,**options)
            if self.job:self.job.assign_suspended_pid(self.process.pid)
        except BaseException:
            if self.job:self.job.close()
            if self.process:
                if self.process.poll() is None:self.process.kill()
                self.process.communicate(timeout=5)
            raise

    @property
    def pid(self):return self.process.pid

    @property
    def returncode(self):return self.process.returncode

    def poll(self):
        result=self.process.poll()
        if result is not None and self.job:self.job.close()
        return result

    def communicate(self,input=None,timeout=None):
        self.poll()
        try:
            result=self.process.communicate(input=input,timeout=timeout)
            if self.job:self.job.close()
            return result
        except subprocess.TimeoutExpired:
            self.poll() # Parent exit must not leave a descendant holding the pipe.
            raise

    def terminate_tree(self):
        if self.job:
            self.job.terminate();self.job.close()
        else:
            try:os.killpg(self.pid,signal.SIGKILL)
            except ProcessLookupError:pass
