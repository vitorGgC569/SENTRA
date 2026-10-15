import React, { useEffect, useRef, useState } from 'react';

const KEY = 'sentra_computer_panel_width';
export function ComputerResizeHandle({ panelRef, expanded }) {
  const [width, setWidth] = useState(() => { try { return Math.max(280, Math.min(900, Number(localStorage.getItem(KEY)) || 330)); } catch { return 330; } });
  const [maximum, setMaximum] = useState(900), drag = useRef(null);
  useEffect(() => {
    const panel = panelRef.current, workspace = panel?.closest('.dot-computer-workspace');
    if (!workspace) return;
    const screen = matchMedia('(min-width:1001px)');
    const update = () => {
      const max = Math.max(280, workspace.clientWidth - 320); setMaximum(max);
      if (!expanded && screen.matches) workspace.style.gridTemplateColumns = 'minmax(0, 1fr) ' + Math.min(width, max) + 'px';
      else workspace.style.removeProperty('grid-template-columns');
    };
    const resize = new ResizeObserver(update); resize.observe(workspace); screen.addEventListener('change', update); update();
    return () => { resize.disconnect(); screen.removeEventListener('change', update); workspace.style.removeProperty('grid-template-columns'); };
  }, [width, expanded, panelRef]);
  useEffect(() => { try { localStorage.setItem(KEY, String(width)); } catch { /* Resizing still works without storage. */ } }, [width]);
  const change = value => setWidth(Math.max(280, Math.min(maximum, value)));
  return <div className="dot-computer-resize" role="separator" aria-label="Largura do painel do computador" aria-orientation="vertical"
    aria-valuemin={280} aria-valuemax={maximum} aria-valuenow={Math.min(width, maximum)} tabIndex={expanded ? -1 : 0} hidden={expanded}
    onKeyDown={event => {
      const next = event.key === 'ArrowLeft' ? width + (event.shiftKey ? 50 : 20) : event.key === 'ArrowRight' ? width - (event.shiftKey ? 50 : 20) : event.key === 'Home' ? 280 : event.key === 'End' ? maximum : null;
      if (next !== null) { event.preventDefault(); change(next); }
    }}
    onPointerDown={event => { if (event.button !== 0) return; event.preventDefault(); drag.current = { x: event.clientX, width }; event.currentTarget.setPointerCapture(event.pointerId); }}
    onPointerMove={event => { if (drag.current) change(drag.current.width + drag.current.x - event.clientX); }}
    onPointerUp={event => { drag.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }}
    onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }} />;
}
