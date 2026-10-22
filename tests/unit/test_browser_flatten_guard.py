from types import SimpleNamespace
from sentra_executors import playwright_browser as browser


def test_current_cdp_guards_target_before_releasing_flat_startup_pause(monkeypatch):
    events=[];backend=object.__new__(browser.PlaywrightBrowserBackend)
    backend._manual_attaching=set();backend._guarded_targets=set();backend._channels={}
    session=SimpleNamespace(binding=SimpleNamespace(max_frames=4),channels=[],record=lambda *a,**kw:events.append(a[0]))
    backend._contexts={'context':session}
    class Root:
        def send(self,method,params):
            events.append(method)
            if method=='Target.attachToTarget':
                # Chromium emits another attached event before the RPC reply.
                backend._attached(self,{'sessionId':'child','targetInfo':{'targetId':'page','browserContextId':'context','type':'page'}})
                return {'sessionId':'child'}
    class Channel:
        def __init__(self,*args):self.session_id=args[2];self.session=args[3]
        def send(self,method,params=None):events.append(method)
    monkeypatch.setattr(browser,'_TargetChannel',Channel)
    backend._root=Root()
    backend._attached(backend._root,{'sessionId':'flat','targetInfo':{'targetId':'page','browserContextId':'context','type':'page'}})
    assert events.index('Fetch.enable')<events.index('Target.detachFromTarget')
    assert 'Runtime.runIfWaitingForDebugger' not in events
    assert len(session.channels)==1
    backend._detached({'sessionId':'child'})
    assert not backend._guarded_targets and not session.channels
