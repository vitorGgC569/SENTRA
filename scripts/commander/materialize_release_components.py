"""Explicit final-phase entrypoint; this file has not been executed."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from scripts.commander.release_components import stage_runtime_components


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--final-phase-authorized',action='store_true')
    parser.add_argument('--staging',type=Path,required=True)
    for component in ('quickjs','hcs','rustdesk'): parser.add_argument('--'+component,type=Path,required=True)
    args = parser.parse_args()
    if not args.final_phase_authorized: parser.error('global implementation/integration must finish before materialization')
    result = stage_runtime_components(args.staging,{name:getattr(args,name) for name in ('quickjs','hcs','rustdesk')})
    print(json.dumps(result,sort_keys=True))
    return 0

if __name__ == '__main__': raise SystemExit(main())
