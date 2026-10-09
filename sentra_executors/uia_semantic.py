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
        if not self.key or not self.automation_id or not self.control_type or not set(self.actions)<={'read','invoke','set_value','toggle','select'}:
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
        if not set(self.actions)<={'observe','wait','read','invoke','set_value','toggle','select','screenshot'} or not 2<=self.timeout_seconds<=120 or not 1<=self.max_text_chars<=65536 or type(self.require_foreground_for_mutation) is not bool:
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
        window=app.window(handle=expected.hwnd).wrapper_object()
        if window.window_text()!=profile['window_title']:raise ExecutorFailure('uia_window_title_changed')
        def locate(selector):
            check()
            if window.window_text()!=profile['window_title']:raise ExecutorFailure('uia_window_title_changed')
            search=dict(auto_id=selector['automation_id'],control_type=selector['control_type'])
            if selector.get('name') is not None:search['title']=selector['name']
            control=window.child_window(**search).wrapper_object();info=control.element_info
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
                text=control.window_text();limit=profile['max_text_chars']
                try:value=control.iface_value.CurrentValue
                except Exception:value=None
                return {'selector_key':selector['key'],'runtime_id':runtime,'automation_id':info.automation_id,
                    'control_type':info.control_type,'name':info.name[:limit],
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
                except Exception:observations.append({'selector_key':selector['key'],'available':False})
            check();return {'elements':observations,'process_identity':asdict(expected),'desktop':native_desktop_identity(desktop),
                            'pywinauto_version':version,'os_isolation_attested':False}
        if action=='screenshot':
            check();image=window.capture_as_image();checkpoint()
            image.save(args['_temporary_output'],format='PNG');check()
            return {'width':image.width,'height':image.height,'window_only':True,'coordinate_input_used':False}
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
            except Exception as exc:raise ExecutorFailure('uia_pattern_action_failed',uncertain=True) from exc
        check();return {'element':record(selector,control,runtime),'action':action,'coordinate_input_used':False,
                        'effect_semantically_verified':action=='set_value' and control.iface_value.CurrentValue==args.get('value')}


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
            if action not in {'observe','wait','screenshot'}:
                ref=refs.get(a['reference'])
                if ref is None:raise ExecutorFailure('uia_reference_not_owned_or_observation_changed')
                worker_args.update(_selector_key=ref['selector_key'],_expected_runtime_id=ref['runtime_id'])
            elif action=='wait':worker_args['_selector_key']=a['selector_key']
            def invoke(arguments):
                return self.runner.invoke(self.python,('-m','sentra_executors.uia_guest_worker'),input_document={
                    'profile':profile,'arguments':arguments},timeout_seconds=b.timeout_seconds-1)
            if action=='screenshot':
                metadata={}
                def produce(path):metadata.update(invoke(dict(worker_args,_temporary_output=str(path))))
                def verify(path):
                    if path.read_bytes()[:8]!=b'\x89PNG\r\n\x1a\n':raise ExecutorFailure('uia_screenshot_not_png')
                artifact=atomic_output(b.paths,a['output'],produce,verify,max_output_bytes=16*1024*1024)
                return dict(metadata,artifact=artifact)
            try:result=invoke(worker_args)
            finally:
                if action in {'invoke','set_value','toggle','select'}:refs.clear()
            if action in {'observe','wait','invoke','set_value','toggle','select'}:
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
    def __init__(self,*,machine_id,owner_principal_id,bindings,policy=None,backend=None):
        if len({b.capability_id for b in bindings})!=len(bindings):raise ValueError('duplicate_uia_capability')
        super().__init__(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings={b.capability_id:b for b in bindings},policy=policy)
        self.backend=backend or SemanticUIABackend()
    def _validate(self,request,b):
        a=dict(request.arguments);action=a.get('action')
        fields={'observe':set(),'wait':{'selector_key','expected','wait_seconds'},'screenshot':{'output'},'set_value':{'reference','value'}}.get(action,{'reference'})
        if action not in b.actions or set(a)-({'action'}|fields):raise ValueError('uia_action_or_fields_denied')
        if action=='wait':
            if a.get('selector_key') not in {s.key for s in b.selectors} or not isinstance(a.get('expected'),dict) or not a['expected'] or set(a['expected'])-{'text','value','enabled','visible'}:
                raise ValueError('bounded_semantic_condition_required')
            if not 0<a.get('wait_seconds',5)<=min(10,b.timeout_seconds-2):raise ValueError('uia_wait_limit')
        elif action=='screenshot':
            path=b.paths.resolve(a.get('output'),write=True)
            if path.suffix.lower()!='.png':raise ValueError('uia_png_output_required')
            a['output']=str(path)
        elif action!='observe' and (type(a.get('reference')) is not str or not a['reference']):raise ValueError('uia_reference_required')
        if action=='set_value' and (type(a.get('value')) is not str or len(a['value'])>b.max_text_chars):raise ValueError('uia_value_limit')
        a['_scope']=SessionScope.from_request(request).key;a['_operation_id']=request.operation_id
        return json.loads(json.dumps(a,allow_nan=False))
    def _run(self,b,a):return self.backend.run(b,a)


def declare_semantic_windows_machine(*,machine_id,owner_principal_id,bindings,policy=None,backend=None):
    executor=SemanticUIAExecutor(machine_id=machine_id,owner_principal_id=owner_principal_id,bindings=bindings,policy=policy,backend=backend)
    return declaration(executor,bindings,'UIA semantic patterns with live process/session/desktop identity')
