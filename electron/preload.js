'use strict'

// 预加载脚本：只向渲染进程暴露受控的桌面能力，不开放 Node API。
const { contextBridge, ipcRenderer, webUtils } = require('electron')

contextBridge.exposeInMainWorld('haruka', {
  backendInfo: () => ipcRenderer.invoke('backend-info'),
  restartBackend: () => ipcRenderer.invoke('restart-backend'),
  runtimeSettings: () => ipcRenderer.invoke('runtime-settings'),
  discoverRuntime: () => ipcRenderer.invoke('runtime-discover'),
  checkRuntime: (settings) => ipcRenderer.invoke('runtime-check', settings),
  applyRuntime: (settings) => ipcRenderer.invoke('runtime-apply', settings),
  chooseDirectory: (title) => ipcRenderer.invoke('choose-directory', title),
  chooseFile: (options) => ipcRenderer.invoke('choose-file', options),
  revealInFolder: (targetPath) => ipcRenderer.invoke('reveal-in-folder', targetPath),
  openDir: (dirPath) => ipcRenderer.invoke('open-dir', dirPath),
  filePath: (file) => webUtils.getPathForFile(file),
  saveAudio: (name, bytes) => ipcRenderer.invoke('save-audio', name, bytes),
})
