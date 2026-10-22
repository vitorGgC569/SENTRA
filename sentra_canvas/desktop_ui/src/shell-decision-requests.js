// Coucou presentation uses the existing SENTRA request journal and read-only
// permission inspection. No approval body or command is stored in this layer.
import { WorkspaceRequestJournal } from './workspace/request-journal.js';

const PREFIX = 'coordinator-approval:';
export class DecisionRequests {
  constructor(projectId, { bridge, journal, crypto = globalThis.crypto } = {}) {
    this.projectId = projectId;
    this.bridge = bridge;
    this.crypto = crypto;
    this.journal = journal || new WorkspaceRequestJournal('decision-center:' + projectId);
  }
  pending() {
    return this.journal.list().map(row => {
      if (row.action !== 'coordinator_approval_reply' || row.project_id !== this.projectId || !row.space_id || !row.slot.startsWith(PREFIX)) {
        throw Error('O diário de decisões precisa de revisão. Nenhum pedido será reenviado.');
      }
      const scope = JSON.parse(row.slot.slice(PREFIX.length));
      if (!Array.isArray(scope) || scope.length !== 2 || scope.some(id => typeof id !== 'string' || !id || id.length > 200)) {
        throw Error('Escopo da decisão pendente inválido.');
      }
      return { ...row, approval_id: scope[0], conversation_id: scope[1] };
    });
  }
  async send(item, answer) {
    if (!this.journal.locks?.request) throw Error('Este ambiente não permite coordenar decisões entre janelas.');
    return this.journal.locks.request(this.journal.key + ':decision', { ifAvailable: true }, async lock => {
      if (!lock) throw Error('Outra janela está respondendo. Atualize a leitura antes de continuar.');
      return this.sendExclusive(item, answer);
    });
  }
  async sendExclusive(item, answer) {
    if (!['approve', 'reject'].includes(answer) || !item?.approval_id || !item?.conversation_id || !item?.space_id) {
      throw Error('O pedido ainda não tem um escopo confirmado.');
    }
    if (this.pending().some(row => row.approval_id === item.approval_id)) {
      throw Error('Consulte a decisão pendente antes de enviar outra resposta.');
    }
    const request = { action: 'coordinator_approval_reply', project_id: this.projectId,
      space_id: item.space_id, approval_id: item.approval_id, answer, request_key: this.crypto.randomUUID() };
    const slot = PREFIX + JSON.stringify([item.approval_id, item.conversation_id]);
    await this.journal.begin(request, slot);
    // Once recorded, even an untyped transport failure retains the selector.
    // A new window can inspect it; it must never reconstruct and resend it.
    await this.bridge(request);
    return this.inspect(item.approval_id);
  }
  async inspect(approvalId) {
    const row = this.pending().find(value => value.approval_id === approvalId);
    if (!row) throw Error('Não há decisão registrada para consultar.');
    const result = await this.bridge({ action: 'conversation_permission_status', project_id: this.projectId,
      space_id: row.space_id, conversation_id: row.conversation_id, selector: this.journal.selector(row) });
    if (result?.resolved === true) await this.journal.resolve(row, result);
    return result;
  }
}
