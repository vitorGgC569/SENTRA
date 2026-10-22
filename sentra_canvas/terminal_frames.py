"""Uniform bounded read frames for live, daemon and restored terminal history."""
MAX_FRAME_CHARS=16000


def bounded_output(value):
    text=value.get('text');end=value.get('cursor')
    if not isinstance(text,str) or type(end) is not int or end<len(text) or end>10**12:
        raise RuntimeError('invalid terminal output frame')
    head=value.get('head',end)
    if type(head) is not int or not end<=head<=10**12:raise RuntimeError('invalid terminal output head')
    start=end-len(text);part=text[:MAX_FRAME_CHARS];cursor=start+len(part)
    return {**value,'text':part,'cursor':cursor,'head':head,
        'has_more':cursor<head or bool(value.get('has_more'))}
