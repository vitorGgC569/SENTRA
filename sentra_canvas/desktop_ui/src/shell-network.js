const READS = new Set(['network_home', 'network_status']);
const FIELDS = {
  network_home: [],
  network_status: ['space_id', 'dot_id'],
  network_enable: ['space_id', 'dot_id'],
  network_disable: ['space_id', 'dot_id'],
  network_invite: ['space_id', 'dot_id', 'address', 'port', 'confirmation'],
  network_revoke: ['space_id', 'dot_id', 'node_id'],
  network_converse: ['space_id', 'dot_id', 'node_id', 'text'],
  network_delegate: ['space_id', 'dot_id', 'node_id', 'task'],
  network_review: ['space_id', 'dot_id', 'node_id', 'intent_id'],
};
const HIDDEN = ['grant_id', 'grant', 'fingerprint', 'identity', 'private_key', 'mesh_key', 'renderer', 'bind', 'host', 'path', 'sqlite'];
const FLAGS = ['physical_proof', 'vpn_is_authorization', 'public_bind', 'database_exposed', 'image_installer'];

function text(value) {
  return typeof value === 'string' ? value.trim() : '';
}

export function networkPayload(action, input = {}) {
  const allowed = FIELDS[action];
  if (!allowed) throw new Error('Ação de rede desconhecida.');
  const source = input && typeof input === 'object' ? input : {};
  const params = {};
  for (const key of allowed) {
    if (source[key] === undefined || source[key] === null || source[key] === '') continue;
    params[key] = source[key];
  }
  const required = allowed.filter(key => key !== 'confirmation');
  for (const key of required) {
    if (params[key] === undefined) throw new Error('Falta o escopo desta ação.');
  }
  if (action === 'network_invite') {
    params.address = text(params.address);
    const port = Number(params.port);
    if (!params.address || !Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error('O convite precisa do endereço e da porta do outro computador.');
    }
    params.port = port;
    if (params.confirmation !== undefined) params.confirmation = text(params.confirmation);
  }
  const payload = { action, ...params };
  if (!READS.has(action)) payload.request_key = text(source.request_key) || crypto.randomUUID();
  for (const key of HIDDEN) delete payload[key];
  return payload;
}

function peerOf(dot) {
  return {
    node_id: text(dot?.node_id),
    state: text(dot?.state),
    paired: dot?.paired === true,
    invite: text(dot?.invite),
    disconnected: dot?.disconnected !== false,
    execution_authorized: false,
  };
}

export function presentNetwork(document) {
  const view = {
    renderer: 'lumen',
    physical_proof: false,
    vpn_is_authorization: false,
    public_bind: false,
    database_exposed: false,
    image_installer: false,
    enabled: false,
    listening: false,
    disconnected: true,
    configured: false,
    configuration: null,
    peers: [],
    available: false,
    rejected: '',
  };
  if (document == null) return view;
  if (document.query_failed === true || document.status === 'unavailable') {
    return { ...view, readFailure: true };
  }
  const peers = Array.isArray(document.peers) ? document.peers : (document.schema === 1 && Array.isArray(document.dots) ? document.dots : null);
  if (!peers || (document.schema !== undefined && document.schema !== 1 && document.renderer !== 'lumen')) {
    return { ...view, rejected: 'documento recusado' };
  }
  const configuration = document.configuration && typeof document.configuration === 'object'
    ? {
      source: text(document.configuration.source),
      adapter_kind: text(document.configuration.adapter_kind),
      interface_configured: document.configuration.interface_configured === true,
      settings_enabled: document.configuration.settings_enabled === true,
    }
    : null;
  return {
    ...view,
    available: true,
    enabled: document.enabled === true,
    listening: document.listening === true,
    disconnected: document.disconnected !== false && document.listening !== true,
    configured: document.configured === true || document.enabled === true,
    configuration,
    peers: peers.map(peerOf),
  };
}

export function presentNetworkResult(value) {
  const source = value && typeof value === 'object' ? value : {};
  const hidden = {};
  for (const key of HIDDEN) hidden[key] = false;
  const receipt = source.receipt && typeof source.receipt === 'object' ? source.receipt : null;
  const failed = source.success === false || source.status === 'admission_failed' || source.status === 'uncertain' || source.query_failed === true || source.effect_uncertain === true;
  return {
    ...hidden,
    renderer: 'lumen',
    physical_proof: false,
    ok: !failed && source.status === 'committed',
    status: text(source.status),
    enabled: source.enabled === true,
    listening: source.listening === true,
    disconnected: source.disconnected === true,
    readFailure: source.query_failed === true || source.status === 'admission_failed',
    effectUncertain: source.effect_uncertain === true || source.status === 'uncertain',
    mayResend: false,
    automaticRetry: false,
    peer: source.peer && typeof source.peer === 'object' ? peerOf(source.peer) : null,
    inReview: receipt?.work_item_state === 'IN_REVIEW',
    artifact: typeof source.result_document === 'string' ? source.result_document : '',
    intentId: text(receipt?.intent_id),
  };
}
