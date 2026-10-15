const SURFACES = ['connector', 'skill', 'plugin', 'automation', 'marketplace', 'visual'];

export function presentOptional(document) {
  const view = {
    projection: 'optional-surfaces',
    available: false,
    items: [],
    homologated: false,
    closed_by_absence: false,
    grants_created: false,
    downloads: false,
    accounts_opened: false,
  };
  if (!document) return view;
  if (document.query_failed === true || document.status === 'unavailable') return { ...view, readFailure: true };
  if (Array.isArray(document.connectors) || Array.isArray(document.models) || document.catalog) {
    const reason = value => value === 'WEIGHTS_ABSENT' ? 'Pesos ainda não estão neste computador.'
      : value === 'RUNTIME_ABSENT' ? 'O runtime ainda não está neste computador.'
      : value === 'RUNTIME_PRESENT' ? 'Runtime presente.' : '';
    return {
      ...view,
      available: true,
      connectors: (document.connectors || []).filter(row => row && typeof row === 'object').map(row => ({
        id: typeof row.id === 'string' ? row.id : 'conector',
        account_needs: typeof row.account_needs === 'string' ? row.account_needs : '',
        enabled: row.enabled === true,
        account_present: row.account_present === true,
      })),
      models: (document.models || []).filter(row => row && typeof row === 'object').map(row => ({
        id: typeof row.id === 'string' ? row.id : 'modelo',
        reason: reason(row.reason),
      })),
      catalog: Array.isArray(document.catalog?.items) ? document.catalog.items.map(item => (
        typeof item === 'string' ? item : (item?.name || item?.title || item?.id || '')
      )).filter(Boolean) : [],
    };
  }
  if (!Array.isArray(document.items)) return view;
  return {
    ...view,
    available: true,
    items: document.items.filter(item => SURFACES.includes(item?.surface)).map(item => ({
      surface: item.surface,
      present: item.present === true,
      available: item.available === true,
      opt_in_required: true,
      reason: typeof item.reason === 'string' ? item.reason : '',
      needs: typeof item.needs === 'string' ? item.needs : '',
      closed_by_absence: false,
      capability_closed: false,
      grants_created: false,
      homologated: false,
    })),
  };
}
