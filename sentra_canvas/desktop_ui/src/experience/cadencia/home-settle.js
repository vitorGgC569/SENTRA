/** Home may show rows only after a settled read. A failed read is not an empty project. */

export const HOME_LOADING = 'Consultando seu trabalho…';

export function homeFrame({ loading = false, settled = false, readError = '', empty = false } = {}) {
  const failed = typeof readError === 'string' && readError.trim() !== '';
  if (!settled && (loading || !failed)) {
    return {
      show: 'loading',
      text: HOME_LOADING,
      showBoard: false,
      showEmpty: false,
      showFailure: false,
      mutation: false,
      resend: false,
    };
  }
  if (failed) {
    return {
      show: 'read-error',
      headline: 'A consulta não chegou.',
      happened: 'A leitura da Home não assentou.',
      safeNext: 'Consulte de novo. Esta falha não esvazia o projeto.',
      showBoard: Boolean(settled),
      showEmpty: false,
      showFailure: true,
      mutation: false,
      resend: false,
    };
  }
  return {
    show: empty ? 'empty' : 'ready',
    text: '',
    showBoard: true,
    showEmpty: Boolean(empty),
    showFailure: false,
    mutation: false,
    resend: false,
  };
}
