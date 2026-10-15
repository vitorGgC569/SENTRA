import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';

// A bounded DOM for large loaded transcripts. Canonical messages stay in the
// parent's store; search and export still operate on that complete loaded set.
export function ShellMessageWindow({ items, scrollRef, children, follow, enabled = true, label = 'Mensagens carregadas' }) {
  const host = useRef(null), sizes = useRef(new Map()), observers = useRef(new Map());
  const [revision, measure] = useState(0), [viewport, setViewport] = useState({ top: 0, height: 800 });
  const previousLayout = useRef(null), frame = useRef(null), followRef = useRef(follow);
  const readingAnchor = useRef(null), previousMode = useRef(null);
  followRef.current = follow;
  const keys = useMemo(() => items.map(item => item.message_id), [items]);
  const layout = useMemo(() => {
    const offsets = [0];
    for (const id of keys) offsets.push(offsets[offsets.length - 1] + (sizes.current.get(id) || 240));
    return offsets;
  }, [keys, revision]);
  const virtual = enabled && items.length > 80;
  useEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const update = () => {
      if (frame.current !== null) return;
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        if (!host.current) return;
        const bounds = root.getBoundingClientRect();
        const anchor = [...host.current.querySelectorAll('.shell-message-slot')].find(node => node.getBoundingClientRect().bottom > bounds.top);
        if (anchor) readingAnchor.current = { id: anchor.dataset.messageId, offset: anchor.getBoundingClientRect().top - bounds.top };
        const top = Math.max(0, root.getBoundingClientRect().top - host.current.getBoundingClientRect().top);
        setViewport({ top, height: root.clientHeight });
      });
    };
    root.addEventListener('scroll', update, { passive: true });
    const resize = new ResizeObserver(update); resize.observe(root); update();
    return () => { root.removeEventListener('scroll', update); resize.disconnect(); cancelAnimationFrame(frame.current); frame.current = null; };
  }, [scrollRef, virtual]);
  useEffect(() => () => { for (const observer of observers.current.values()) observer.disconnect(); observers.current.clear(); }, []);
  useLayoutEffect(() => {
    const root = scrollRef.current;
    if (!root) return;
    const previous = previousLayout.current;
    if (followRef.current) root.scrollTop = root.scrollHeight;
    else if (previousMode.current !== null && previousMode.current !== virtual && readingAnchor.current && host.current) {
      const anchor = [...host.current.querySelectorAll('.shell-message-slot')].find(node => node.dataset.messageId === readingAnchor.current.id);
      if (anchor) root.scrollTop += anchor.getBoundingClientRect().top - root.getBoundingClientRect().top - readingAnchor.current.offset;
    }
    else if (previous && host.current) {
      const top = Math.max(0, root.getBoundingClientRect().top - host.current.getBoundingClientRect().top);
      let anchor = 0;
      while (anchor < previous.keys.length - 1 && previous.offsets[anchor + 1] <= top) anchor++;
      const next = keys.indexOf(previous.keys[anchor]);
      if (next >= 0) root.scrollTop += layout[next] - previous.offsets[anchor];
    }
    previousLayout.current = { keys, offsets: layout };
    previousMode.current = virtual;
  }, [layout, keys, scrollRef, virtual]);
  let start = 0, end = items.length;
  if (virtual) {
    while (start < items.length - 1 && layout[start + 1] < viewport.top - 900) start++;
    end = start;
    while (end < items.length && layout[end] < viewport.top + viewport.height + 900) end++;
    end = Math.min(items.length, Math.max(end, start + 8));
    if (previousMode.current === false && readingAnchor.current) {
      const index = keys.indexOf(readingAnchor.current.id);
      if (index >= 0) { start = Math.max(0, index - 5); end = Math.min(items.length, index + 8); }
    }
  }
  function observe(id, element) {
    observers.current.get(id)?.disconnect(); observers.current.delete(id);
    if (!element || !virtual) return;
    const observer = new ResizeObserver(() => {
      const height = element.getBoundingClientRect().height;
      if (height <= 0 || Math.abs((sizes.current.get(id) || 240) - height) < 1) return;
      sizes.current.set(id, height); measure(value => value + 1);
    });
    observer.observe(element); observers.current.set(id, observer);
  }
  return <div ref={host} className="shell-message-window" role="list" aria-label={label} data-windowed={virtual ? 'true' : 'false'} data-total={items.length}>
    {virtual && <div aria-hidden="true" style={{ height: layout[start] }} />}
    {items.slice(start, end).map((item, index) => <div key={item.message_id} className="shell-message-slot" ref={element => observe(item.message_id, element)}
      data-message-id={item.message_id} aria-posinset={start + index + 1} aria-setsize={items.length} role="listitem">{children(item)}</div>)}
    {virtual && <div aria-hidden="true" style={{ height: layout[items.length] - layout[end] }} />}
  </div>;
}
