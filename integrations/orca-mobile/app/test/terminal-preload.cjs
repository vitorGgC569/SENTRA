'use strict';
const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('ReactNativeWebView',{postMessage:value=>ipcRenderer.send('terminal-message',value)});
