'use strict';
const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('sentraIsland', Object.freeze({
  subscribe: callback => {
    const receive = (_event, value) => callback(value);
    ipcRenderer.on('sentra:presence:snapshot', receive);
    ipcRenderer.send('sentra:presence:ready');
    return () => ipcRenderer.removeListener('sentra:presence:snapshot', receive);
  },
  expand: expanded => ipcRenderer.send('sentra:presence:expand', expanded === true),
  geometry: value => ipcRenderer.send('sentra:presence:geometry', value),
  activate: (action, dotId) => ipcRenderer.send('sentra:presence:activate', { action, dotId }),
}));
