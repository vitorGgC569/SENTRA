"""Signed endpoint metadata for a single terminal's limited Canvas capability."""
import hashlib
import hmac
import json
import os
from pathlib import Path


def process_stamp(pid):
    if type(pid) is not int or pid <= 0:
        raise ValueError('invalid broker PID')
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)]
        kernel.GetProcessTimes.restype=wintypes.BOOL
        kernel.GetExitCodeProcess.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        handle=kernel.OpenProcess(0x1000,False,pid)
        if not handle:raise OSError('broker process unavailable')
        try:
            times=[wintypes.FILETIME() for _ in range(4)];exit_code=wintypes.DWORD()
            if not kernel.GetProcessTimes(handle,*[ctypes.byref(value) for value in times]):
                raise OSError('broker process identity unavailable')
            if not kernel.GetExitCodeProcess(handle,ctypes.byref(exit_code)) or exit_code.value!=259:
                raise OSError('broker process ended')
            return 'windows:'+str((times[0].dwHighDateTime<<32)|times[0].dwLowDateTime)
        finally:kernel.CloseHandle(handle)
    if Path('/proc/sys/kernel/random/boot_id').is_file():
        stat=Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()
        if stat[0]=='Z':raise OSError('broker process ended')
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()+':'+stat[19]
    raise RuntimeError('durable Canvas binding process identity unsupported')


def signature(value,token):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    return hmac.new(token.encode(),raw,hashlib.sha256).hexdigest()


def read_binding(path,token,workspace):
    path=Path(path)
    if not path.is_absolute():
        raise ValueError('bounded absolute Canvas binding required')
    with path.open('rb') as source:raw=source.read(8193)
    if len(raw)>8192:raise ValueError('bounded absolute Canvas binding required')
    value=json.loads(raw.decode('utf-8'))
    if not isinstance(value,dict):raise ValueError('invalid Canvas binding')
    proof=value.pop('signature',None)
    expected={'version','binding_id','terminal_id','workspace','port','runtime_id','broker_pid','process_stamp'}
    if (set(value)!=expected or value['version']!=1 or value['workspace']!=workspace or
            type(value['port']) is not int or not 1<=value['port']<=65535 or
            not isinstance(proof,str) or not hmac.compare_digest(signature(value,token),proof)):
        raise PermissionError('Canvas binding identity or signature changed')
    if value['process_stamp']!=process_stamp(value['broker_pid']):
        raise PermissionError('Canvas binding process identity changed')
    return value
