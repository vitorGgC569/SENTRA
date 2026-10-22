'use strict';
// Startup diagnostics for an explicitly isolated development window only.
// Records resource paths and presentation readiness, never tokens or content.
const fs = require('node:fs');
const path = require('node:path');
function installEvaluationDiagnostics(app, directory) {
  const append = value => fs.appendFileSync(path.join(directory, 'resource-diagnostics.jsonl'), JSON.stringify(value) + '\n');
  app.on('web-contents-created', (_event, contents) => {
    const localPath = value => { try { return new URL(value).pathname; } catch { return ''; } };
    contents.session.webRequest.onErrorOccurred(details => {
      const resource = localPath(details.url);
      if (resource.startsWith('/desktop-assets/')) append({path: resource, error: details.error});
    });
    contents.session.webRequest.onCompleted(details => {
      const resource = localPath(details.url);
      if (resource.startsWith('/desktop-assets/')) append({path: resource, status: details.statusCode, type: details.resourceType});
    });
    contents.once('did-finish-load', () => {
      let attempts = 0;
      const inspect = async () => {
        if (contents.isDestroyed()) return;
        try {
          const readiness = await contents.executeJavaScript(`(() => {
            const shell = document.querySelector('.opendots-shell');
            const mascots = [...document.querySelectorAll('.shell-mascot img')];
            const styled = !!shell && getComputedStyle(shell).display === 'flex';
            const workspace = document.querySelector('.sentra-workspace');
            return {styled, title: document.title, workspaceMode: workspace?.dataset.mode || null,
              workspaceReady: !!workspace?.querySelector('.sw-pane'),
              welcomeVisible: !!workspace?.querySelector('.sw-welcome'),
              explorerVisible: !!workspace?.querySelector('.sw-explorer'),
              membersVisible: !!workspace?.querySelector('.sw-members'),
              mascotCount: mascots.length,
              mascotsReady: mascots.length > 0 && mascots.every(image => image.complete && image.naturalWidth > 0),
              loadError: !!document.querySelector('.desktop-load-error'),
              hasLocalCredential: !!sessionStorage.getItem('sentra_native_token'),
              projectOptions: document.querySelector('.shell-project-select')?.options?.length || 0,
              mobileButton: [...document.querySelectorAll('button')].some(button => button.textContent.includes('Celular · QR Code') || (button.getAttribute('aria-label') || '').includes('QR Code'))};
          })()`);
          fs.writeFileSync(path.join(directory, 'display-readiness.json'), JSON.stringify(readiness));
          if ((!readiness.styled || !readiness.mascotsReady || !readiness.workspaceReady) && ++attempts < 10) setTimeout(inspect, 2000);
          else if (!readiness.workspaceReady && !contents.isDestroyed()) {
            fs.writeFileSync(path.join(directory,'startup-diagnostic.png'),(await contents.capturePage()).toPNG());
          }
        } catch { append({readiness: 'unavailable'}); }
      };
      setTimeout(inspect, 2000);
    });
  });
}
module.exports = {installEvaluationDiagnostics};
