const { contextBridge } = require('electron')

contextBridge.exposeInMainWorld('printfilmStandalone', {
  platform: process.platform,
  isStandalone: true,
})
