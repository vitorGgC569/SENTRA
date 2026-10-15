export function closeUpdateMenuOnEscape(event, menu) {
  if (!event || event.key !== 'Escape' || !menu || menu.open !== true) return false;
  menu.open = false;
  if (typeof event.preventDefault === 'function') event.preventDefault();
  const summary = typeof menu.querySelector === 'function' ? menu.querySelector('summary') : null;
  if (summary && typeof summary.focus === 'function') summary.focus();
  return true;
}
