'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('sentraDesktopPresence', Object.freeze({
  available: true,
  publish: value => ipcRenderer.send('sentra:presence:publish', value),
  toggle: () => ipcRenderer.send('sentra:presence:toggle'),
  onAction: callback => {
    const receive = (_event, value) => callback(value);
    ipcRenderer.on('sentra:presence:action', receive);
    ipcRenderer.send('sentra:presence:owner-ready');
    return () => ipcRenderer.removeListener('sentra:presence:action', receive);
  },
}));
