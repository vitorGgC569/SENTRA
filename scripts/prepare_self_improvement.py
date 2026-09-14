"""Create a tiny, fresh Git repository for the first real self-improvement pilot.

Only explicit source files enter it; no old clone, credentials or live extension
is modified. The harness lives in this trusted controller and patches cannot
change it. --run invokes the existing operational OMA, never a second engine.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import hashlib
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OBJECTIVE = (
    "Use exactly ONE task. Improve edge_extension/content-script.js so no partial or contaminated prompt "
    "can be submitted. Compare the COMPLETE composer text to the expected prompt after fill and immediately "
    "before EACH button/form/Enter submission (including after awaits). On mismatch throw a clear error, "
    "not swallowed by catch/fallback. Preserve normal Unicode/multiline sends, stale-draft clearing, version "
    "1.3.9, other primitive operations and bounded retries. No quota bypass, no new network access. "
    "Read the code and tests through repository directives. Provide a minimal unified diff, changing ONLY "
    "edge_extension/content-script.js. The fixed tests cannot be changed; [[TEST|all]] runs them in Docker. "
    "Do not propose changes to configuration, harness, policies, promotion, or other files."
)

POLICY_OBJECTIVE = (
    "Use exactly ONE task. Harden input validation in orchestrator/compute_policy.py. "
    "initial_agents, when present, must be a Python int (not bool or float) and match the initial role count. "
    "escalation, when present and not None, must be a dict even if the value is falsey. "
    "When add_agents appears alongside add_roles, validate it as a nonnegative int (not bool/float) "
    "before checking count agreement. Raise ValueError for these invalid configurations. Preserve "
    "existing valid configurations, None/default behavior, role aliases, deduplication, critical escalation, "
    "max_agents caps, zero additions and the existing bounded semantics of large add_agents values. "
    "Do not mutate input configuration. Read the real source and frozen tests via repository directives. "
    "Read orchestrator/compute_policy.py and tests/test_compute_policy_contract.py; these are short. "
    "Return a minimal unified diff changing ONLY orchestrator/compute_policy.py. "
    "The test harness, models.py and isolated package bootstrap cannot change. [[TEST|all]] runs frozen "
    "tests in Docker. No shell, new dependencies, test weakening, policy bypass or self-promotion. "
    "This is an isolated two-module source snapshot; the controlling engine remains outside it."
)


async def main(argv=None):
    import yaml
    from main import main_async
    from orchestrator.models import Candidate
    from orchestrator.verification import CandidateVerifier
    from workspace.docker_runner import prepare_execution

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true', help='Send a bounded real-agent task via the paired Edge bridge')
    parser.add_argument('--case', choices=['prompt-integrity', 'compute-policy'], default='prompt-integrity')
    parser.add_argument('--agents', type=int, choices=[5, 6], default=5)
    parser.add_argument('--provider', choices=['extension', 'openai'], default='extension')
    parser.add_argument('--model', default='gpt-5.6-sol', help='Exact API model for explicit live calibration')
    parser.add_argument('--time-limit-seconds', type=int, default=900)
    args = parser.parse_args(argv)
    if not 60 <= args.time_limit_seconds <= 1800:
        parser.error('--time-limit-seconds must be 60..1800')
    if args.run and args.provider == 'openai' and not os.environ.get('OPENAI_API_KEY'):
        raise ValueError('OPENAI_API_KEY is not configured; no live calibration was started')
    execution = await prepare_execution({'backend':'docker'})
    folder = ROOT/'.oma'/'self-improvement'/(args.case+'-'+uuid.uuid4().hex[:8])
    repo = folder/'repository'
    (repo/'tests').mkdir(parents=True)
    if args.case == 'compute-policy':
        target = 'orchestrator/compute_policy.py'
        (repo/'orchestrator').mkdir()
        (repo/'orchestrator'/'__init__.py').write_text('"""Isolated pilot package; production modules unchanged."""\n')
        (repo/'orchestrator'/'models.py').write_bytes((ROOT/'orchestrator'/'models.py').read_bytes())
        test_name = 'test_compute_policy_contract.py'
        profiles = {'all':['python','-B','-m','pytest','-q','tests/'+test_name]}
        objective = POLICY_OBJECTIVE
    else:
        target = 'edge_extension/content-script.js'
        (repo/'edge_extension').mkdir()
        test_name = 'prompt_integrity.test.cjs'
        profiles = {'all':['node','--test','tests/'+test_name]}
        version = re.search(r'OMA_CS_VERSION\s*=\s*[\'"]([^\'"]+)', (ROOT/target).read_text(encoding='utf-8'))
        if not version:
            raise ValueError('cannot identify source version; refuse a stale objective')
        objective = OBJECTIVE.replace('1.3.9', version[1])
    source = (ROOT/target).read_bytes()
    (repo/target).write_bytes(source)
    frozen_tests = (ROOT/'self_improvement'/'fixtures'/test_name).read_bytes()
    (repo/'tests'/test_name).write_bytes(frozen_tests)
    subprocess.run(['git','-c','init.templateDir=','init','-b','codex/'+args.case,str(repo)],check=True,capture_output=True)
    roles = ['logic','requirements','adversarial'] + (['security'] if args.agents == 6 else [])
    config = {
        'routing':{'worker':args.provider,'reviewer':args.provider,'fallback':None,
                   'openai_model':args.model, 'openai_key_env':'OPENAI_API_KEY'},
        'browser':{'relay_base':'http://127.0.0.1:8765','timeout_seconds':180},
        'validation':{'execution':execution,'commands':['[[TEST|all]]'], 'profiles':profiles,
                      'timeout_seconds':45,'allowed_patch_paths':[target]},
        'orchestrator':{'max_rounds':2,'max_parallel_sessions':1,'no_progress_limit':2},
        # Calibrado por scripts/calibrate_budgets.py sobre runs reais
        # (runs/budget-calibration.json): task ~= 150k, secundaria 200k.
        # Budgets minúsculos continuam cobertos pelos testes unitários de budget.
        # Lapidação máxima: rounds suficientes para o loop executor↔validadores
        # convergir; estagnação (mesma rejeição) para cedo sozinha. Humanos só
        # veem CANDIDATE_READY ou esgotamento real.
        'oma':{'max_repair_rounds':4,'global_task_budget':1,'max_inflight_requests':2,
               'token_budget_master':20000,'token_budget_secondary':200000,'task_token_budget':150000,
               'fixed_conversations':True, 'inter_call_delay_s':30, 'max_seats':args.agents,
               'stagnation_limit':5,
               'validators_required':len(roles), 'minimum_approvals':len(roles)-1,
               'compute_policy':{'initial_agents':args.agents, 'initial_roles':roles,
                                 'max_agents':args.agents,
                                 'escalation':{reason:{'add_agents':0} for reason in
                                               ('disagreement','low_confidence','critical_task')}}},
        'default_acceptance_criteria':[objective],
    }
    config_path = folder/'operator-config.yaml'
    config_path.write_text(yaml.safe_dump(config,sort_keys=False,allow_unicode=True),encoding='utf-8')
    baseline = await CandidateVerifier(repo, profiles=profiles, timeout=30, execution=execution).verify(Candidate(task_id='baseline'))
    (folder/'baseline-tests.json').write_text(json.dumps(baseline,indent=2),encoding='utf-8')
    command = [sys.executable,'-B',str(ROOT/'main.py'),'--config',str(config_path),
               '--workspace',str(repo),'--job-id',args.case,'--prompt',objective]
    (folder/'pilot.json').write_text(json.dumps({'repository':str(repo),'execution':execution,'command':command,
                                               'baseline_passed':baseline['all_passed'], 'max_conversations':args.agents if args.provider == 'extension' else 0,
                                               'provider':args.provider, 'requested_model':args.model if args.provider == 'openai' else None,
                                               'time_limit_seconds':args.time_limit_seconds,
                                               'target':target, 'source_sha256':hashlib.sha256(source).hexdigest(),
                                               'test_sha256':hashlib.sha256(frozen_tests).hexdigest()},indent=2),encoding='utf-8')
    print(json.dumps({'repository':str(repo),'config':str(config_path),'baseline_passed':baseline['all_passed'],
                      'run_id':args.case,'image':execution['image'], 'max_conversations':args.agents},indent=2),flush=True)
    if args.run:
        if baseline['all_passed']:
            raise ValueError('baseline already passes; no live calls for an unmeasured improvement')
        return await asyncio.wait_for(main_async(command[3:]), timeout=args.time_limit_seconds)
    return 0


if __name__ == '__main__':
    for stream in (sys.stdout,sys.stderr):
        if hasattr(stream,'reconfigure'):
            stream.reconfigure(encoding='utf-8',errors='replace')
    raise SystemExit(asyncio.run(main()))
