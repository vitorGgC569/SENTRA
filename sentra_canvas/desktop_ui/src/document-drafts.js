// Drafts are local recovery data, never a source of server revision or authority.
let database;
function open() {
  if (!database) database = new Promise((resolve, reject) => {
    const request = indexedDB.open('sentra-document-drafts', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('drafts', {keyPath: 'key'});
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(Error('Não foi possível abrir a recuperação de rascunhos.'));
  });
  return database;
}
export const draftKey = (project, space, doc) => JSON.stringify([project, space, doc]);
export async function draftStore(mode, key, value) {
  const db = await open();
  return new Promise((resolve, reject) => {
    const transaction = db.transaction('drafts', mode === 'get' ? 'readonly' : 'readwrite');
    const store = transaction.objectStore('drafts');
    const request = mode === 'get' ? store.get(key) : mode === 'delete' ? store.delete(key) : store.put({key, ...value, savedAt: Date.now()});
    let result;
    request.onsuccess = () => { result = request.result; };
    transaction.oncomplete = () => resolve(result);
    transaction.onerror = () => reject(Error('Não foi possível preservar o rascunho neste computador.'));
    transaction.onabort = transaction.onerror;
  });
}
