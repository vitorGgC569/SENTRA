from contextlib import contextmanager
from types import SimpleNamespace
import pytest
from sentra_executors.virtualbox_vm import VirtualBoxClient
from sentra_executors.input_control import needs_input
from sentra_canvas.shell_actor import _vm_input_identity


@pytest.mark.parametrize('fail_after_press',[False,True])
def test_host_releases_pointer_even_when_press_confirmation_is_lost(fail_after_press):
    events=[]
    class Mouse:
        def PutMouseEventAbsolute(self,x,y,w,h,buttons):
            events.append(buttons)
            if buttons==1 and fail_after_press:raise OSError('lost confirmation after physical press')
    console=SimpleNamespace(Mouse=Mouse(),Display=SimpleNamespace(GetScreenResolution=lambda _: (1280,800)))
    client=VirtualBoxClient(path='fixture-only')
    @contextmanager
    def owned_console(binding):yield console
    client.console=owned_console
    arguments={'action':'input.tap','x':10,'y':20}
    binding=SimpleNamespace(vm_id='fixture-vm')
    if fail_after_press:
        with pytest.raises(OSError):client.input(binding,arguments)
    else:assert client.input(binding,arguments)['pointer_released']
    assert events==[1,0]
    assert needs_input(SimpleNamespace(arguments=arguments))
    assert _vm_input_identity(arguments)==('mouse','tap:10:20',None)
