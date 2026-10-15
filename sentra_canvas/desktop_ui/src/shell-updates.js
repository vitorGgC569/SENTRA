export const BUNDLE_VERSION = '0.1.0';

const KINDS = {
  data: {
    kind: 'data', label: 'Atualizar dados', reloadsWindow: false, installsBits: false, compilesCode: false, touchesUserData: false,
    notice: 'Dados consultados de novo. A versão instalada e o código local não foram alterados.',
  },
  code: {
    kind: 'code', label: 'Atualizar código local', reloadsWindow: true, installsBits: false, compilesCode: true, touchesUserData: false,
    notice: 'Isto recompila a interface local. Não é uma atualização da versão instalada e não apaga conversas, Dots ou VMs.',
  },
  version: {
    kind: 'version', label: 'Versão instalada', reloadsWindow: false, installsBits: true, compilesCode: false, touchesUserData: false,
    notice: 'A versão instalada só muda pelo instalador do Windows. Este comando não atualiza dados nem recompila a interface.',
  },
};

export function classifyUpdate(kind) {
  if (!KINDS[kind]) throw new Error('Tipo de atualização desconhecido.');
  return KINDS[kind];
}

export function versionDecision({ installed = null, available = null, dataRefresh = false } = {}) {
  if (dataRefresh) return { apply: false, reason: 'Atualizar dados não troca a versão instalada.' };
  if (typeof installed !== 'string' || !installed || typeof available !== 'string' || !available) {
    return { apply: false, reason: 'Não há marcador de versão instalada nesta janela. A troca fica no instalador e não mexe em dados, VMs ou conversas.' };
  }
  if (installed === available) return { apply: false, reason: 'A versão instalada já é ' + installed + '. Nenhum dado foi atualizado.' };
  return { apply: true, reason: 'A versão do pacote (' + available + ') é diferente da instalada (' + installed + '). A troca não apaga dados, VMs nem conversas.' };
}