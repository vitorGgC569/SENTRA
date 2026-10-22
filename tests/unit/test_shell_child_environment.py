import os
import pytest
from sentra_canvas.shell_environment import shell_child_environment


@pytest.mark.skipif(os.name!='nt',reason='Windows module-path composition')
def test_powershell_child_uses_persisted_roots_without_changing_parent_or_policy():
    inherited={'PSMODULEPATH':r'C:\temporary-development-host\Modules','SYSTEMROOT':r'C:\Windows',
        'USERPROFILE':r'C:\Users\owner','PSExecutionPolicyPreference':'AllSigned','PATH':'original'}
    snapshot=dict(inherited)
    value=shell_child_environment('powershell',inherited,read_paths=lambda:[r'%SYSTEMROOT%\System32\WindowsPowerShell\v1.0\Modules',
        r'%PSModulePath%;%USERPROFILE%\CustomModules'])
    assert value['PSModulePath']==r'C:\Windows\System32\WindowsPowerShell\v1.0\Modules;C:\Users\owner\CustomModules'
    assert inherited==snapshot and value['PSExecutionPolicyPreference']=='AllSigned' and value['PATH']=='original'
    assert 'PSMODULEPATH' not in value


@pytest.mark.skipif(os.name!='nt',reason='Windows module-path composition')
def test_powershell_initializes_defaults_when_no_persisted_override_exists():
    environment={'PSModulePath':'temporary','KEEP':'value'}
    assert shell_child_environment('powershell',environment,read_paths=lambda:[])=={'KEEP':'value'}
    assert shell_child_environment('cmd',environment)==environment
