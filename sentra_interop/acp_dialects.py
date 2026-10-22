"""Presentation only; dialect output never proves an operation succeeded.

OpenCode normalization adapted from ORCA at 70b2197c, MIT, Lovecast Inc.
Source: src/main/acp/acp-dialects/opencode-dialect.ts; vendor/orca/LICENSE.
"""


def normalize_update(dialect,event):
    if dialect!='opencode' or event.get('sessionUpdate') not in {'tool_call','tool_call_update'}:
        return event
    raw=event.get('rawOutput')
    if not isinstance(raw,dict):return event
    metadata=raw.get('metadata',{})
    if not isinstance(metadata,dict):return event
    value=dict(raw)
    output=raw.get('output') if isinstance(raw.get('output'),str) else metadata.get('output')
    if isinstance(output,str) and not any(raw.get(k) is not None for k in ('stdout','stderr','output_for_prompt')):
        value['stdout']=output
    if type(metadata.get('exit')) is int and not any(raw.get(k) is not None for k in ('exitCode','exit_code')):
        value['exitCode']=metadata['exit']
    return {**event,'rawOutput':value}
