import React, { useEffect, useRef, useState } from 'react';
import { BaseEdge } from '@xyflow/react';
import { useReducedMotion } from './experience/cadencia/index.js';

// A damped spring on the cable's control points. Endpoints always stay attached
// to their ports; only the visual cable bends and settles during a node move.
function controls(sx, sy, tx, ty) {
  const reach = Math.max(70, Math.min(260, Math.abs(tx - sx) * .45));
  const sag = Math.min(95, Math.hypot(tx - sx, ty - sy) * .1);
  return [sx + reach, sy + sag, tx - reach, ty + sag];
}
function curve(sx, sy, tx, ty, c) {
  return `M ${sx},${sy} C ${c[0]},${c[1]} ${c[2]},${c[3]} ${tx},${ty}`;
}
export function CanvasCable({ id, sourceX, sourceY, targetX, targetY, selected, markerEnd }) {
  const reduced = useReducedMotion();
  const target = controls(sourceX, sourceY, targetX, targetY);
  const spring = useRef({ points: target, velocity: [0, 0, 0, 0] });
  const [points, setPoints] = useState(target);
  useEffect(() => {
    const goal = controls(sourceX, sourceY, targetX, targetY);
    if (reduced) { spring.current = { points: goal, velocity: [0, 0, 0, 0] }; setPoints(goal); return; }
    let frame, previous, elapsed = 0;
    const tick = time => {
      const dt = Math.min((time - (previous ?? time - 16)) / 1000, .032);
      previous = time; elapsed += dt;
      let unsettled = false;
      const value = spring.current;
      value.points = value.points.map((point, index) => {
        const delta = goal[index] - point;
        value.velocity[index] += (delta * 180 - value.velocity[index] * 22) * dt;
        if (Math.abs(delta) > .15 || Math.abs(value.velocity[index]) > .15) unsettled = true;
        return point + value.velocity[index] * dt;
      });
      if (unsettled && elapsed < 2) { setPoints([...value.points]); frame = requestAnimationFrame(tick); }
      else { spring.current = { points: goal, velocity: [0, 0, 0, 0] }; setPoints(goal); }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [sourceX, sourceY, targetX, targetY, reduced]);
  return <BaseEdge id={id} path={curve(sourceX, sourceY, targetX, targetY, reduced ? target : points)} markerEnd={markerEnd} interactionWidth={22} className={'shell-physical-cable' + (selected ? ' is-selected' : '')} />;
}
export function CanvasConnection({ fromX, fromY, toX, toY }) {
  return <path d={curve(fromX, fromY, toX, toY, controls(fromX, fromY, toX, toY))} className="shell-physical-cable is-connecting" fill="none" />;
}
