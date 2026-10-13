// Convert only validated, local Smart UI choices into an ordinary user draft.
// Nothing is sent or executed until the person explicitly presses Enviar.
export function prepareSentraUiReply(spec, answers = {}) {
  if (spec?.version !== 1 || !Array.isArray(spec.elements)) return null;
  const result = [];
  for (const element of spec.elements) {
    if (element.type === 'choice') {
      const selected = answers[element.id] ?? element.default ?? element.options[0];
      if (!element.options.includes(selected)) return null;
      result.push({id: element.id, label: element.label, selection: selected});
    } else if (element.type === 'checklist') {
      const selected = element.items.filter((_, i) => answers[element.id]?.[i] === true);
      result.push({id: element.id, label: element.label, selected});
    }
  }
  if (!result.length) return null;
  const draft = 'Minhas respostas ao painel "' + spec.title + '":\n' +
    JSON.stringify({version: 1, answers: result}, null, 2);
  return draft.length <= 4000 ? draft : null;
}
