/* Local load diagnostics only. No credentials, API calls or recovery side effects. */
(() => {
  function show(message) {
    const root = document.getElementById('desktop-root');
    if (!root || root.querySelector('.desktop-shell')) return;
    const safe = String(message || 'Os componentes locais não foram carregados.')
      .replace(/(?:Bearer\s+|token=)[^\s&#]+/gi, '[credencial omitida]').slice(0, 400);
    root.replaceChildren();
    const box = document.createElement('section'); box.className = 'desktop-load-error';
    const title = document.createElement('strong'); title.textContent = 'Não foi possível abrir o desktop';
    const detail = document.createElement('p'); detail.textContent = safe;
    const reload = document.createElement('button'); reload.textContent = 'Recarregar a superfície';
    reload.addEventListener('click', () => location.reload());
    box.append(title, detail, reload); root.append(box);
  }
  window.addEventListener('error', event => {
    if (event.target?.tagName === 'SCRIPT') show('Não foi possível carregar um dos arquivos locais do desktop.');
    else show(event.message);
  }, true);
  window.addEventListener('unhandledrejection', event => show(event.reason?.message));
})();
