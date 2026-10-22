"""Isolated validation host for the pinned official OpenCode binary.

This is not the installed SENTRA account/profile. Central ACP process ownership
includes the child; stdin/stdout are exclusively the provider's ACP stream.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--binary',type=Path,required=True)
    parser.add_argument('--state',type=Path,required=True)
    args=parser.parse_args()
    state=args.state.resolve();state.mkdir(parents=True,exist_ok=True)
    for name in ('home','config','data','cache','temp','appdata','localappdata'):(state/name).mkdir(exist_ok=True)
    # Deliberately construct the child environment: never inherit provider keys,
    # Web cookies, proxy credentials, plugins or the user's OpenCode settings.
    environment={key:os.environ[key] for key in ('SYSTEMROOT','WINDIR','COMSPEC','PATHEXT') if key in os.environ}
    if os.name=='nt':
        import ctypes
        directory=ctypes.create_unicode_buffer(32768)
        if not ctypes.windll.kernel32.GetWindowsDirectoryW(directory,len(directory)):
            raise RuntimeError('Windows system directory unavailable')
        environment.update({'SYSTEMROOT':directory.value,'WINDIR':directory.value,
            'PATH':str(Path(directory.value)/'System32'),'COMSPEC':str(Path(directory.value)/'System32'/'cmd.exe')})
    environment.update({'HOME':str(state/'home'),'USERPROFILE':str(state/'home'),
        'APPDATA':str(state/'appdata'),'LOCALAPPDATA':str(state/'localappdata'),
        'XDG_CONFIG_HOME':str(state/'config'),'XDG_DATA_HOME':str(state/'data'),
        'XDG_CACHE_HOME':str(state/'cache'),'TEMP':str(state/'temp'),'TMP':str(state/'temp'),
        'OPENCODE_DISABLE_AUTOUPDATE':'1','OPENCODE_DISABLE_DEFAULT_PLUGINS':'1',
        'OPENCODE_DISABLE_LSP_DOWNLOAD':'1','OPENCODE_CONFIG_CONTENT':json.dumps({'permission':'ask','autoupdate':False})})
    with (state/'provider-stderr.log').open('ab') as diagnostics:
        code=subprocess.call([str(args.binary.resolve(strict=True)),'acp'],env=environment,stderr=diagnostics)
        diagnostics.write(('\nProvider exit code: '+str(code)+'\n').encode())
        raise SystemExit(code)


if __name__=='__main__':main()
