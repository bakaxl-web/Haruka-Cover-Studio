'use strict'

// 以标准 Electron 模式启动应用。
// 必须删除 ELECTRON_RUN_AS_NODE：某些宿主机（或 IDE/Agent 环境）会设置它，
// 导致 Electron 以纯 Node 模式运行，require('electron') 拿不到 ipcMain 等 API。
const { spawn } = require('node:child_process')

const electronBinary = require('electron')

const env = { ...process.env }
delete env.ELECTRON_RUN_AS_NODE

const child = spawn(electronBinary, ['.'], {
  stdio: 'inherit',
  env,
  windowsHide: false,
})

child.on('exit', (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal)
    return
  }
  process.exit(code ?? 0)
})
