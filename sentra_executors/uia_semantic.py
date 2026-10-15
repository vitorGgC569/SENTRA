"""Semantic UIA patterns with process/desktop checks; PID scope is NOT OS isolation."""
from __future__ import annotations
import ctypes
import hashlib
import json
import os
import sys
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass,asdict
from pathlib import Path
from .windows_identity import ProcessIdentity,WindowsIdentityProbe
from .identity_sessions import SessionExecutor,SessionScope
from .rpa import AuthorizedPaths,ExecutorFailure,effect_checkpoint,atomic_output
from .guest_process import OwnedProviderRunner,declaration


@dataclass(frozen=True)
class DesktopIdentity:
    machine_guid:str
    session_id:int
    input_desktop_name:str='Default'
    def __post_init__(self):
        if not self.machine_guid or type(self.session_id) is not int or self.session_id<=0 or self.input_desktop_name!='Default':
            raise ValueError('explicit_interactive_desktop_identity_required')


@dataclass(frozen=True)
class UIASelector:
    key:str
    automation_id:str
    control_type:str
    name:str|None=None
    actions:tuple[str,...]=('read',)
    def __post_init__(self):
        if not self.key or not self.automation_id or not self.control_type or not set(self.actions)<={'read','invoke','set_value','toggle','select','input.mouse','input.key'}:
            raise ValueError('exact_semantic_selector_required')


@dataclass(frozen=True)
class SemanticUIABinding:
    capability_id:str
    identity:ProcessIdentity
    window_title:str
    desktop:DesktopIdentity
    selectors:tuple[UIASelector,...]
    paths:AuthorizedPaths
    actions:tuple[str,...]=('observe','wait','read','screenshot')
    timeout_seconds:float=20
    max_text_chars:int=8192
    require_foreground_for_mutation:bool=True
    def __post_init__(self):
        if not self.capability_id or not self.window_title or not self.selectors or len(self.selectors)>256 or len({s.key for s in self.selectors})!=len(self.selectors):
            raise ValueError('invalid_semantic_uia_binding')
        if not set(self.actions)<={'observe','observe.hybrid','wait','read','invoke','set_value','toggle','select','screenshot','input.mouse','input.key'} or not 2<=self.timeout_seconds<=120 or not 1<=self.max_text_chars<=65536 or type(self.require_foreground_for_mutation) is not bool:
            raise ValueError('invalid_semantic_uia_limits')


def native_desktop_identity(expected:DesktopIdentity):
    if sys.platform!='win32':raise ExecutorFailure('windows_interactive_uia_required')
    import winreg
    from ctypes import wintypes
    effect_checkpoint()
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,r'SOFTWARE\Microsoft\Cryptography',0,winreg.KEY_READ|winreg.KEY_WOW64_64KEY) as key:
        guid=winreg.QueryValueEx(key,'MachineGuid')[0]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True);user=ctypes.WinDLL('user32',use_last_error=True)
    sid=wintypes.DWORD();kernel.ProcessIdToSessionId.argtypes=(wintypes.DWORD,ctypes.POINTER(wintypes.DWORD))
    if not kernel.ProcessIdToSessionId(os.getpid(),ctypes.byref(sid)):raise ExecutorFailure('interactive_session_identity_unavailable')
    user.OpenInputDesktop.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD);user.OpenInputDesktop.restype=wintypes.HANDLE
    handle=user.OpenInputDesktop(0,False,1)
    if not handle:raise ExecutorFailure('input_desktop_locked_or_unavailable')
    try:
        name=ctypes.create_unicode_buffer(256);size=wintypes.DWORD()
        user.GetUserObjectInformationW.argtypes=(wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD))
        if not user.GetUserObjectInformationW(handle,2,name,ctypes.sizeof(name),ctypes.byref(size)):
            raise ExecutorFailure('input_desktop_identity_unavailable')
        if str(guid).lower()!=expected.machine_guid.lower() or sid.value!=expected.session_id or name.value!=expected.input_desktop_name:
            raise ExecutorFailure('machine_session_or_input_desktop_changed')
        return {'machine_guid':str(guid),'session_id':sid.value,'input_desktop':name.value,'os_isolation_attested':False}
    finally:
        user.CloseDesktop.argtypes=(wintypes.HANDLE,);user.CloseDesktop(handle)


@contextmanager
def desktop_input_lock(desktop):
    """Kernel mutex in the actual interactive session, including guest workers.

    Distinct SENTRA machines/controllers cannot overlap input patterns. A mutex
    is exclusion, not OS confinement or permission to automate a desktop.
    """
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    kernel.WaitForSingleObject.restype = wintypes.DWORD
    kernel.ReleaseMutex.argtypes = (wintypes.HANDLE,)
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    name = 'Local\\SENTRA-Input-' + hashlib.sha256(json.dumps(asdict(desktop), sort_keys=True).encode()).hexdigest()
    handle = kernel.CreateMutexW(None, False, name)
    if not handle:
        raise ExecutorFailure('desktop_input_mutex_unavailable')
    owned = False
    try:
        state = kernel.WaitForSingleObject(handle, 0)
        owned = state in {0, 0x80}  # WAIT_ABANDONED owns the mutex; revalidate target.
        if not owned:
            raise ExecutorFailure('interactive_desktop_input_owned_elsewhere')
        yield
    finally:
        if owned:
            kernel.ReleaseMutex(handle)
        kernel.CloseHandle(handle)


def _rect_tuple(value):
    if hasattr(value, 'left'):
        return (int(value.left), int(value.top), int(value.right), int(value.bottom))
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ExecutorFailure('uia_rectangle_required')
    return tuple(int(item) for item in value)


def pointer_target(element_rect, window_rect):
    """Center of the element, refused when it falls outside the bound window."""
    left, top, right, bottom = _rect_tuple(element_rect)
    if right - left < 1 or bottom - top < 1:
        raise ExecutorFailure('uia_element_rectangle_empty')
    x, y = (left + right) // 2, (top + bottom) // 2
    wl, wt, wr, wb = _rect_tuple(window_rect)
    if not (wl <= x < wr and wt <= y < wb):
        raise ExecutorFailure('uia_click_outside_window')
    return x, y


def keyboard_post_state(sent_units, expected, observed):
    if type(sent_units) is not int or sent_units < 1:
        return 'not_sent'
    if observed == expected:
        return 'verified'
    return 'uncertain'


def _input_struct():
    from ctypes import wintypes
    class MOUSEINPUT(ctypes.Structure):
        _fields_ = (('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                    ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD),
                    ('dwExtraInfo', ctypes.c_void_p))
    class KEYBDINPUT(ctypes.Structure):
        _fields_ = (('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                    ('time', wintypes.DWORD), ('dwExtraInfo', ctypes.c_void_p))
    class INPUTUNION(ctypes.Union):
        _fields_ = (('mi', MOUSEINPUT), ('ki', KEYBDINPUT))
    fields = [('type', wintypes.DWORD), ('union', INPUTUNION)]
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        fields = [('type', wintypes.DWORD), ('padding', wintypes.DWORD), ('union', INPUTUNION)]
    class INPUT(ctypes.Structure):
        _fields_ = fields
    return INPUT, MOUSEINPUT, KEYBDINPUT


def send_mouse_click(x, y):
    """One left click at a point already checked against the bound window."""
    if sys.platform != 'win32':
        raise ExecutorFailure('windows_interactive_uia_required')
    if type(x) is not int or type(y) is not int:
        raise ExecutorFailure('uia_pointer_not_integral')
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetSystemMetrics.argtypes = (ctypes.c_int,)
    user.GetSystemMetrics.restype = ctypes.c_int
    origin_x, origin_y = user.GetSystemMetrics(76), user.GetSystemMetrics(77)
    width, height = user.GetSystemMetrics(78), user.GetSystemMetrics(79)
    if width <= 1 or height <= 1:
        raise ExecutorFailure('uia_virtual_screen_unavailable')
    absolute_x = int(round((x - origin_x) * 65535 / (width - 1)))
    absolute_y = int(round((y - origin_y) * 65535 / (height - 1)))
    INPUT, MOUSEINPUT, _ = _input_struct()
    move = 0x0001
    down = 0x0002
    up = 0x0004
    absolute = 0x8000
    virtual_desk = 0x4000
    def packet(flags):
        item = INPUT()
        item.type = 0
        item.union.mi = MOUSEINPUT(absolute_x, absolute_y, 0, flags, 0, None)
        return item
    user.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
    user.SendInput.restype = ctypes.c_uint
    pressed = packet(move | absolute | virtual_desk | down)
    released = packet(move | absolute | virtual_desk | up)
    sent = user.SendInput(2, (INPUT * 2)(pressed, released), ctypes.sizeof(INPUT))
    if sent != 2:
        if sent == 1:
            user.SendInput(1, ctypes.byref(released), ctypes.sizeof(INPUT))
        raise ExecutorFailure('uia_mouse_dispatch_failed', uncertain=sent > 0)
    return {'x': x, 'y': y, 'events': 2}


def focused_child(window_hwnd):
    """Focus of the window's UI thread. Null when that thread has no focus."""
    if sys.platform != 'win32':
        raise ExecutorFailure('windows_interactive_uia_required')
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
    user.GetWindowThreadProcessId.restype = wintypes.DWORD
    thread = user.GetWindowThreadProcessId(window_hwnd, None)
    class GUITHREADINFO(ctypes.Structure):
        _fields_ = (('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                    ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                    ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                    ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                    ('rcCaret', wintypes.RECT))
    info = GUITHREADINFO()
    info.cbSize = ctypes.sizeof(GUITHREADINFO)
    user.GetGUIThreadInfo.argtypes = (wintypes.DWORD, ctypes.POINTER(GUITHREADINFO))
    if not user.GetGUIThreadInfo(thread, ctypes.byref(info)):
        return 0
    return int(info.hwndFocus or 0)


def send_chars_to_control(handle, text):
    """Key messages to one already focused control. No global keyboard replay."""
    if sys.platform != 'win32':
        raise ExecutorFailure('windows_interactive_uia_required')
    if (not isinstance(text, str) or not text or len(text) > 65536 or
            any(ord(ch) == 0 or ord(ch) > 0xFFFF for ch in text)):
        raise ExecutorFailure('uia_keyboard_text_rejected')
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    user.SendMessageW.restype = ctypes.c_ssize_t
    for ch in text:
        user.SendMessageW(handle, 0x0102, ord(ch), 1)
    return len(text)


def control_window_text(handle):
    if sys.platform != 'win32':
        raise ExecutorFailure('windows_interactive_uia_required')
    from ctypes import wintypes
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPWSTR)
    user.SendMessageW.restype = ctypes.c_ssize_t
    buffer = ctypes.create_unicode_buffer(4096)
    user.SendMessageW(handle, 0x000D, 4096, buffer)
    return buffer.value


def send_unicode_text(text):
    """Type BMP characters. A partial send is uncertain and is not retried here."""
    if sys.platform != 'win32':
        raise ExecutorFailure('windows_interactive_uia_required')
    if (not isinstance(text, str) or not text or len(text) > 65536 or
            any(ord(ch) == 0 or ord(ch) > 0xFFFF for ch in text)):
        raise ExecutorFailure('uia_keyboard_text_rejected')
    user = ctypes.WinDLL('user32', use_last_error=True)
    INPUT, _, KEYBDINPUT = _input_struct()
    unicode_flag = 0x0004
    key_up = 0x0002
    user.SendInput.argtypes = (ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int)
    user.SendInput.restype = ctypes.c_uint
    sent_units = 0
    for ch in text:
        def packet(flags, scan=ord(ch)):
            item = INPUT()
            item.type = 1
            item.union.ki = KEYBDINPUT(0, scan, flags, 0, None)
            return item
        down, up = packet(unicode_flag), packet(unicode_flag | key_up)
        sent = user.SendInput(2, (INPUT * 2)(down, up), ctypes.sizeof(INPUT))
        sent_units += sent
        if sent != 2:
            if sent == 1:
                user.SendInput(1, ctypes.byref(up), ctypes.sizeof(INPUT))
            raise ExecutorFailure('uia_keyboard_dispatch_failed', uncertain=True)
    return sent_units


class UIAProbeEngine:
    """One process/COM apartment per request. No keyboard/mouse fallback."""
    def perform(self,profile,args,checkpoint):
        if sys.platform!='win32':raise ExecutorFailure('windows_interactive_uia_required')
        try:
            from pywinauto.application import Application
        except ImportError as exc:raise ExecutorFailure('pywinauto_provider_missing') from exc
        import importlib.metadata
        version=importlib.metadata.version('pywinauto')
        expected=ProcessIdentity(**profile['identity']);desktop=DesktopIdentity(**profile['desktop'])
        def check():
            checkpoint();native_desktop_identity(desktop)
            if WindowsIdentityProbe()(expected.pid,expected.hwnd)!=expected:raise ExecutorFailure('uia_process_identity_changed')
            sid=ctypes.c_ulong()
            if not ctypes.windll.kernel32.ProcessIdToSessionId(expected.pid,ctypes.byref(sid)) or sid.value!=desktop.session_id:
                raise ExecutorFailure('uia_target_outside_interactive_session')
        check();app=Application(backend='uia').connect(process=expected.pid,timeout=1)
        spec=app.window(handle=expected.hwnd)
        window=spec.wrapper_object()
        if window.window_text()!=profile['window_title']:raise ExecutorFailure('uia_window_title_changed')
        def locate(selector):
            check()
            if window.window_text()!=profile['window_title']:raise ExecutorFailure('uia_window_title_changed')
            search=dict(auto_id=selector['automation_id'],control_type=selector['control_type'])
            if selector.get('name') is not None:search['title']=selector['name']
            control=spec.child_window(**search).wrapper_object();info=control.element_info
            info.set_cache_strategy(cached=False)
            if int(info.process_id)!=expected.pid or int(control.top_level_parent().handle)!=expected.hwnd:
                raise ExecutorFailure('uia_control_outside_bound_window')
            runtime=list(info.runtime_id)
            if not runtime:raise ExecutorFailure('uia_runtime_identity_unavailable')
            return control,runtime
        def record(selector,control,runtime):
            # Property caching is confined to one observation; action lookup is fresh.
            info=control.element_info;info.set_cache_strategy(cached=True)
            try:
                try:is_password=bool(info.element.CurrentIsPassword)
                except Exception:is_password=True  # Unknown privacy property cannot expose a value.
                text='' if is_password else (control.window_text() or '');limit=profile['max_text_chars']
                try:value=None if is_password else control.iface_value.CurrentValue
                except Exception:value=None
                name=info.name or ''
                return {'selector_key':selector['key'],'runtime_id':runtime,'automation_id':info.automation_id,
                    'control_type':info.control_type,'name':name[:limit],
                    'text':text[:limit],'text_truncated':len(text)>limit,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
                    'value':value[:limit] if isinstance(value,str) else None,
                    'value_truncated':isinstance(value,str) and len(value)>limit,
                    'enabled':bool(control.is_enabled()),'visible':bool(control.is_visible()),
                    'rectangle':[info.rectangle.left,info.rectangle.top,info.rectangle.right,info.rectangle.bottom],
                    'available_actions':selector['actions']}
            finally:info.set_cache_strategy(cached=False)
        action=args['action'];selectors=profile['selectors']
        if action=='observe':
            observations=[]
            for selector in selectors:
                try:control,runtime=locate(selector);observations.append(record(selector,control,runtime))
                except ExecutorFailure:raise
                except Exception as exc:observations.append({'selector_key':selector['key'],'available':False,'error':type(exc).__name__})
            check();return {'elements':observations,'process_identity':asdict(expected),'desktop':native_desktop_identity(desktop),
                            'pywinauto_version':version,'os_isolation_attested':False}
        if action=='screenshot':
            check();image=window.capture_as_image();checkpoint()
            image.save(args['_temporary_output'],format='PNG');check()
            rect=window.rectangle()
            return {'width':image.width,'height':image.height,'window_only':True,'coordinate_input_used':False,
                    'window_rectangle':[rect.left,rect.top,rect.right,rect.bottom]}
        selector=next(s for s in selectors if s['key']==args['_selector_key'])
        if action=='wait':
            deadline=time.monotonic()+args.get('wait_seconds',5)
            while time.monotonic()<deadline:
                check()
                try:
                    control,runtime=locate(selector);observed=record(selector,control,runtime)
                    if all(observed.get(k)==v for k,v in args['expected'].items()):return {'element':observed,'condition_verified':True}
                except ExecutorFailure:raise
                except Exception:pass
                time.sleep(min(.1,max(0,deadline-time.monotonic())))
            raise ExecutorFailure('uia_semantic_condition_timeout')
        control,runtime=locate(selector)
        if runtime!=args['_expected_runtime_id']:raise ExecutorFailure('uia_element_reference_stale')
        if action not in selector['actions']:raise ExecutorFailure('uia_selector_action_denied')
        if action!='read':
            with desktop_input_lock(desktop):
                if not control.is_enabled() or not control.is_visible():raise ExecutorFailure('uia_control_unavailable')
                check()
                if window.window_text()!=profile['window_title']:raise ExecutorFailure('uia_window_title_changed')
                if profile.get('require_foreground_for_mutation',True):
                    from ctypes import wintypes
                    user=ctypes.WinDLL('user32');user.GetForegroundWindow.restype=wintypes.HWND
                    if int(user.GetForegroundWindow() or 0)!=expected.hwnd:raise ExecutorFailure('uia_foreground_hardware_ownership_changed')
                if list(control.element_info.runtime_id)!=runtime:raise ExecutorFailure('uia_element_recreated_before_action')
                try:
                    if action=='invoke':control.iface_invoke.Invoke()
                    elif action=='set_value':control.iface_value.SetValue(args['value'])
                    elif action=='toggle':control.iface_toggle.Toggle()
                    elif action=='select':control.iface_selection_item.Select()
                    elif action=='input.mouse':
                        target=pointer_target(control.rectangle(), window.rectangle())
                        send_mouse_click(*target)
                        if list(control.element_info.runtime_id)!=runtime:
                            raise ExecutorFailure('uia_element_changed_after_mouse',uncertain=True)
                    elif action=='input.key':
                        try:
                            control.element_info.element.SetFocus()
                        except Exception as exc:
                            raise ExecutorFailure('uia_keyboard_focus_failed') from exc
                        target=int(control.handle)
                        if focused_child(expected.hwnd)!=target:
                            raise ExecutorFailure('uia_keyboard_focus_failed')
                        sent=send_chars_to_control(target, args['text'])
                        observed=control_window_text(target)
                        if observed!=args['text']:
                            try:
                                observed=control.iface_value.CurrentValue
                            except Exception:
                                observed=''
                        if keyboard_post_state(sent, args['text'], observed)!='verified':
                            raise ExecutorFailure('uia_keyboard_effect_unverified',uncertain=True)
                    else:
                        raise ExecutorFailure('uia_selector_action_denied')
                except ExecutorFailure:
                    raise
                except Exception as exc:raise ExecutorFailure('uia_pattern_action_failed',uncertain=True) from exc
        verified=(action=='set_value' and control.iface_value.CurrentValue==args.get('value')) or action=='input.key'
        check();return {'element':record(selector,control,runtime),'action':action,
                        'coordinate_input_used':action=='input.mouse',
                        'effect_semantically_verified':verified}


class SemanticUIABackend:
    def __init__(self,runner=None,*,python_executable=None):
        self.runner=runner or OwnedProviderRunner();self.python=python_executable or sys.executable
        self.references={};self.lock=threading.RLock()
    def run(self,b,a):
        with self.lock:
            scope=a['_scope']
            profile={'identity':asdict(b.identity),'desktop':asdict(b.desktop),'window_title':b.window_title,
                     'selectors':[asdict(s) for s in b.selectors],'max_text_chars':b.max_text_chars,
                     'require_foreground_for_mutation':b.require_foreground_for_mutation}
            profile_key=hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()
            refs=self.references.setdefault((scope,profile_key),{})
            action=a['action'];worker_args=dict(a)
            if action not in {'observe','observe.hybrid','wait','screenshot'}:
                ref=refs.get(a['reference'])
                if ref is None:raise ExecutorFailure('uia_reference_not_owned_or_observation_changed')
                worker_args.update(_selector_key=ref['selector_key'],_expected_runtime_id=ref['runtime_id'])
            elif action=='wait':worker_args['_selector_key']=a['selector_key']
            def invoke(arguments):
                remaining=deadline-time.monotonic()
                if remaining<=0:raise ExecutorFailure('uia_compound_observation_deadline')
                return self.runner.invoke(self.python,('-m','sentra_executors.uia_guest_worker'),input_document={
                    'profile':profile,'arguments':arguments},timeout_seconds=remaining)
            deadline=time.monotonic()+b.timeout_seconds-1
            if action in {'screenshot','observe.hybrid'}:
                metadata={}
                observed = invoke(dict(worker_args,action='observe')) if action=='observe.hybrid' else None
                def produce(path):
                    metadata.update(invoke(dict(worker_args,action='screenshot',_temporary_output=str(path))))
                    if observed is not None:
                        current=invoke(dict(worker_args,action='observe'))
                        if current['elements']!=observed['elements']:
                            raise ExecutorFailure('uia_changed_during_hybrid_observation')
                def verify(path):
                    if path.read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise ExecutorFailure('uia_screenshot_not_png')
                artifact=atomic_output(b.paths,a['output'],produce,verify,max_output_bytes=16*1024*1024)
                if observed is not None:
                    refs.clear();revision=uuid.uuid4().hex
                    for element in observed['elements']:
                        if 'runtime_id' in element:
                            token=revision+':'+element['selector_key'];refs[token]=dict(element);element['reference']=token
                    return {**observed,**metadata,'artifact':artifact,'revision':revision,
                            'observation_mode':'uia_and_window_image','coordinate_input_used':False}
                return dict(metadata,artifact=artifact)
            try:result=invoke(worker_args)
            finally:
                if action in {'invoke','set_value','toggle','select','input.mouse','input.key'}:refs.clear()
            if action in {'observe','wait','invoke','set_value','toggle','select','input.mouse','input.key'}:
                refs.clear();revision=uuid.uuid4().hex
                for element in result.get('elements',[result.get('element')]):
                    if element and 'runtime_id' in element:
                        token=revision+':'+element['selector_key'];refs[token]=dict(element);element['reference']=token
                result['revision']=revision
            return result
    def shutdown(self):
        with self.lock:self.references.clear()


class SemanticUIAExecutor(SessionExecutor):
    kind='windows_uia_semantic'
    def __init__(self,*,machine_id,owner_principal_id,bindings,policy=None,backend=None,uncertain=None,
                 placement='host',guest_executor=None):
        if placement not in {'host','guest'}:raise ValueError('placement must be host or guest')
        if len({b.capability_id for b in bindings})!=len(bindings):raise ValueError('duplicate_uia_capability')
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=backend or SemanticUIABackend()
        self.uncertain=uncertain
        self.placement=placement
        self.guest_executor=guest_executor
    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action')
        fields={'observe':set(),'observe.hybrid':{'output'},'wait':{'selector_key','expected','wait_seconds'},'screenshot':{'output'},'set_value':{'reference','value'},'input.mouse':{'reference'},'input.key':{'reference','text'}}.get(action,{'reference'})
        if action not in b.actions or set(a)-({'action'}|fields):raise ValueError('uia_action_or_fields_denied')
        if action=='wait':
            if a.get('selector_key') not in {s.key for s in b.selectors} or not isinstance(a.get('expected'),dict) or not a['expected'] or set(a['expected'])-{'text','value','enabled','visible'}:
                raise ValueError('bounded_semantic_condition_required')
            if not 0<a.get('wait_seconds',5)<=min(10,b.timeout_seconds-2):raise ValueError('uia_wait_limit')
        elif action in {'screenshot','observe.hybrid'}:
            path=b.paths.resolve(a.get('output'),write=True)
            if path.suffix.lower()!='.png':raise ValueError('uia_png_output_required')
            a['output']=str(path)
        elif action!='observe' and (type(a.get('reference')) is not str or not a['reference']):raise ValueError('uia_reference_required')
        if action=='set_value' and (type(a.get('value')) is not str or len(a['value'])>b.max_text_chars):raise ValueError('uia_value_limit')
        if action=='input.key' and (type(a.get('text')) is not str or not a['text'] or len(a['text'])>b.max_text_chars or any(ord(ch)==0 or ord(ch)>0xFFFF for ch in a['text'])):
            raise ValueError('uia_keyboard_text_rejected')
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id
        a['_work_item_id']=request.work_item_id
        return json.loads(json.dumps(a,allow_nan=False))
    def _blocked(self,a):
        if self.uncertain is None or a.get('action') not in {'input.mouse','input.key'}:
            return False
        reference=str(a.get('reference') or '')
        selector=reference.split(':',1)[1] if ':' in reference else ''
        work_item=a.get('_work_item_id')
        if not selector or not work_item:
            raise ExecutorFailure('uia_input_fence_identity_required')
        kind='mouse' if a['action']=='input.mouse' else 'keyboard'
        text=a.get('text') if kind=='keyboard' else None
        return self.uncertain.uncertain_effect(work_item_id=work_item, kind=kind,
                                              selector_key=selector, text=text) is not None
    def _run(self,b,a):
        if self._blocked(a):
            raise ExecutorFailure('uncertain_input_not_repeated',uncertain=True)
        pid=b.identity.pid
        if type(pid) is not int or pid<=0:
            raise ExecutorFailure('guest_process_id_required')
        if a.get('action') in {'input.mouse','input.key'}:
            claimed=a.get('_process_id')
            if claimed is not None and claimed!=pid:
                raise ExecutorFailure('guest_process_id_required')
            a['_process_id']=pid
        if self.placement=='guest':
            from sentra_executors.guest_execution import is_proven_guest_executor
            if not is_proven_guest_executor(self.guest_executor):
                raise ExecutorFailure('guest_executor_unproven',uncertain=True)
            produced=self.guest_executor.execute({
                'action':a.get('action'),'arguments':dict(a),'pid':pid,'placement':'guest'})
            if not isinstance(produced,dict):
                raise ExecutorFailure('guest_executor_result_invalid',uncertain=True)
            exit_code=produced.get('exit_code')
            if (produced.get('execution_uncertain') is True
                    or produced.get('host_subprocess') is True
                    or produced.get('claims_guest_execution') is False
                    or ('exit_code' in produced and (type(exit_code) is not int or exit_code != 0))):
                raise ExecutorFailure('guest_executor_result_invalid',uncertain=True)
            produced=dict(produced)
            produced['execution_surface']='guest'
            produced['host_subprocess']=False
            produced['claims_guest_execution']=True
            return produced
        result=self.backend.run(b,a)
        if isinstance(result,dict):
            result=dict(result)
            if result.get('isolation_boundary'):
                result.setdefault('execution_surface','guest_transport')
                result.setdefault('claims_guest_execution',False)
                result.setdefault('host_subprocess',False)
            else:
                result.setdefault('execution_surface','host')
                result.setdefault('claims_guest_execution',False)
                result.setdefault('host_subprocess',True)
        return result


def declare_semantic_windows_machine(*,machine_id,owner_principal_id,bindings,policy=None,backend=None):
    executor=SemanticUIAExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,policy=policy,backend=backend)
    return declaration(executor,bindings,'UIA semantic patterns with live process/session/desktop identity')
