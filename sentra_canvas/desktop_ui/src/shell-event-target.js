// Keyboard/pointer events may originate on Document or a text node.
export function closestEventTarget(event, selector) {
  const target = event?.target;
  const element = typeof target?.closest === 'function' ? target : target?.parentElement;
  return typeof element?.closest === 'function' ? element.closest(selector) : null;
}
