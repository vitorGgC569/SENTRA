import { useEffect, useState } from 'react';
import { readReducedMotion, watchReducedMotion } from './motion.js';

export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => readReducedMotion());
  useEffect(() => watchReducedMotion(setReduced), []);
  return reduced;
}
