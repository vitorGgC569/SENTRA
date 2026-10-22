"""The JS clients and protected Python journal must hash the same wire intent."""
import json
from pathlib import Path
import shutil
import subprocess


def test_shared_js_canonicalization_matches_python_wire_parser():
    node=shutil.which('node')
    assert node,'Node is required for the desktop/mobile contract acceptance'
    module=Path(__file__).resolve().parents[2]/'integrations/orca-mobile/transport/src/intent-fingerprint.js'
    script='import {canonicalIntent} from '+json.dumps(module.as_uri())+';let raw="";for await(const c of process.stdin)raw+=c;process.stdout.write(JSON.stringify(JSON.parse(raw).map(v=>({wire:JSON.stringify(v),canonical:canonicalIntent(v)}))));'
    vectors=[['ação',{'prompt':'😀\n\t\u007f','z':True,'a':None}],
             ['machine_execute',{'x':1e-6,'y':0.0001,'small':-1.234e-7,'big':1e21,'int':1e20,'zero':-0.0}],
             {'\U00010000':'astral','\ue000':'BMP','nested':[{'b':2,'a':1}]}]
    process=subprocess.run([node,'--input-type=module','-e',script],input=json.dumps(vectors),
                           text=True,encoding='utf-8',capture_output=True,timeout=15,check=True)
    for row in json.loads(process.stdout):
        assert row['canonical']==json.dumps(json.loads(row['wire']),sort_keys=True,separators=(',',':'),allow_nan=False)
