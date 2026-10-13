export function shellCommand(content) {
  const match = /^\/(model|goal)(?:\s+([\s\S]*))?$/i.exec(content.trim());
  if (!match) return null;
  return { name: match[1].toLowerCase(), argument: (match[2] || '').trim() };
}
