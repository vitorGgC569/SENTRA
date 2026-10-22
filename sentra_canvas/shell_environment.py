"""Compose a fresh PowerShell module path from persisted Windows settings.

Temporary module roots injected by a parent development host must not be
mistaken for the selected shell's installed configuration. No policy or
publisher trust is changed; explicit user/machine module roots are retained.
"""
import os
import re


def persisted_module_paths():
    import winreg
    result=[]
    for hive,key in ((winreg.HKEY_LOCAL_MACHINE,r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'),
                     (winreg.HKEY_CURRENT_USER,'Environment')):
        try:
            with winreg.OpenKey(hive,key) as handle:value,kind=winreg.QueryValueEx(handle,'PSModulePath')
        except FileNotFoundError:continue
        if kind not in {winreg.REG_SZ,winreg.REG_EXPAND_SZ} or not isinstance(value,str):
            raise ValueError('invalid persisted PowerShell module path')
        result.append(value)
    return result


def shell_child_environment(shell,inherited,*,read_paths=None):
    environment=dict(inherited)
    if shell not in {'powershell','pwsh'} or os.name!='nt':return environment
    paths=(read_paths or persisted_module_paths)()
    variables={key.upper():value for key,value in environment.items()}
    composed=''
    for value in paths:
        variables['PSMODULEPATH']=composed
        expanded=re.sub(r'%([^%]+)%',lambda match:variables.get(match[1].upper(),match[0]),value)
        composed=expanded if '%PSMODULEPATH%' in value.upper() else ';'.join(part for part in (composed,expanded) if part)
    for key in list(environment):
        if key.upper()=='PSMODULEPATH':del environment[key]
    if composed:environment['PSModulePath']=composed
    # With no persisted value, the selected PowerShell initializes its own
    # defaults. In particular, it does not inherit another PSHOME's modules.
    return environment
