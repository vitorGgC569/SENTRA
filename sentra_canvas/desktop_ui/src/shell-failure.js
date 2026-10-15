export function explainFailure(input) {
  const message = typeof input === 'string' ? input : String(input?.message || '');
  const read = Boolean(input && typeof input === 'object' && input.read);
  if (read) return {
    headline: 'A consulta não chegou ao Canvas',
    happened: message || 'A ligação com o Canvas local falhou.',
    safeNext: 'Consulte de novo. Uma consulta não reenvia uma operação já iniciada.',
    resend: false,
  };
  const uncertain = Boolean(input && typeof input === 'object' && input.uncertain)
    || /incert|uncertain|não confirmad|nao confirmad|sem confirma/i.test(message);
  if (uncertain) return {
    headline: 'A operação não foi confirmada',
    happened: message || 'O SENTRA não recebeu um recibo definitivo.',
    safeNext: 'Consulte a mesma intenção. Não repita o envio.',
    resend: false,
  };
  if (/autoriz|permiss|grant|não foi autorizada|nao foi autorizada/i.test(message)) return {
    headline: 'Sem autorização para esta ação',
    happened: message,
    safeNext: 'Peça acesso neste projeto ou escolha outra ação. A tentativa recusada não é reenviada.',
    resend: false,
  };
  if (/selecione um projeto|outro projeto/i.test(message)) return {
    headline: 'O projeto desta janela não confere',
    happened: message,
    safeNext: 'Selecione o projeto de novo. Nenhuma operação foi repetida.',
    resend: false,
  };
  if (/failed to fetch|network|rede|econnrefused|timeout/i.test(message)) return {
    headline: 'A consulta não chegou ao Canvas',
    happened: message || 'A ligação com o Canvas local falhou.',
    safeNext: 'Consulte de novo. Uma consulta não reenvia uma operação já iniciada.',
    resend: false,
  };
  return {
    headline: 'Não foi possível concluir',
    happened: message || 'O Canvas não devolveu um motivo.',
    safeNext: 'Leia o motivo e consulte o estado antes de qualquer ação nova.',
    resend: false,
  };
}