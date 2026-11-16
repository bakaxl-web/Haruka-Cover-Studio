'use strict'

// Electron 主进程：窗口管理、后端 Python 进程生命周期、原生文件对话框。
const { app, BrowserWindow, ipcMain, dialog, shell } = require('electron')
const path = require('node:path')
const net = require('node:net')
const fs = require('node:fs')
const crypto = require('node:crypto')
const { spawn } = require('node:child_process')
const { readSettings, writeSettings, resolveRuntime, validateRuntime, probePython } = require('./runtime')
const { discoverRuntime } = require('./runtime-discovery')

// 打包后 backend、runtime 位于 resources 目录；开发时位于项目根目录
const PROJECT_ROOT = app.isPackaged ? process.resourcesPath : path.resolve(__dirname, '..')
const BACKEND_DIR = path.join(PROJECT_ROOT, 'backend')
const IS_DEV = process.env.HARUKA_DEV === '1'
const DEV_URL = 'http://127.0.0.1:5173'
const LIGHTWEIGHT = !!require('../package.json').harukaLightweight || process.env.HARUKA_LIGHTWEIGHT === '1'

let mainWindow = null
let backendProcess = null
let backendInfo = null
let runtimeSettings = {}
let startupPromise = Promise.resolve()
let startupError = ''
let applyingRuntime = false
const settingsFile = () => path.join(app.getPath('userData'), 'runtime-settings.json')
const effectiveRuntime = () => resolveRuntime(runtimeSettings, process.env, PROJECT_ROOT, LIGHTWEIGHT)

function findFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    server.unref()
    server.on('error', reject)
    server.listen(0, '127.0.0.1', () => {
      const { port } = server.address()
      server.close(() => resolve(port))
    })
  })
}

// 解析后端解释器：优先环境变量，其次打包运行时，最后开发环境 venv。
function resolveBackendPython(settings) {
  const candidates = [
    settings.backendPython,
    ...(!LIGHTWEIGHT ? [
    process.env.HARUKA_BACKEND_PYTHON,
    path.join(PROJECT_ROOT, 'runtime', 'python-backend', 'Scripts', 'python.exe'),
    path.join(BACKEND_DIR, '.venv', 'Scripts', 'python.exe'),
    ] : []),
  ].filter(Boolean)
  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) return candidate
  }
  throw new Error(
    `找不到后端 Python 解释器，已尝试：\n${candidates.join('\n')}\n请先创建 backend/.venv 或设置 HARUKA_BACKEND_PYTHON。`
  )
}

async function waitForHealth(baseUrl, token, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/api/health`, {
        headers: { 'X-Haruka-Token': token },
      })
      if (response.ok) return await response.json()
    } catch {
      // 后端尚未就绪，继续轮询
    }
    await new Promise((resolve) => setTimeout(resolve, 300))
  }
  throw new Error('后端启动超时：90 秒内未通过健康检查')
}

// 打包后的 venv 记录的是构建机的基础解释器路径，目标机器上不存在。
// 启动时把 home 改写为随包携带的 runtime/python-base，实现解压即用。
function ensureRuntimePortable() {
  if (!app.isPackaged || LIGHTWEIGHT) return
  const runtimeRoot = path.join(process.resourcesPath, 'runtime')
  const basePython = path.join(runtimeRoot, 'python-base')
  if (!fs.existsSync(path.join(basePython, 'python.exe'))) {
    console.error(`[runtime] 缺少自带基础解释器：${basePython}`)
    return
  }
  for (const name of ['python-backend', 'python-rvc']) {
    const configPath = path.join(runtimeRoot, name, 'pyvenv.cfg')
    if (!fs.existsSync(configPath)) continue
    try {
      const original = fs.readFileSync(configPath, 'utf8')
      const updated = original.replace(/^home = .*$/m, `home = ${basePython}`)
      if (updated !== original) fs.writeFileSync(configPath, updated, 'utf8')
    } catch (error) {
      console.error(`[runtime] 重写 pyvenv.cfg 失败：${configPath}`, error)
    }
  }
}

async function startBackend(settings = effectiveRuntime()) {
  const python = resolveBackendPython(settings)
  const port = await findFreePort()
  const token = crypto.randomUUID()
  const baseUrl = `http://127.0.0.1:${port}`
  const outputRoot = process.env.HARUKA_OUTPUT_ROOT || path.join(LIGHTWEIGHT ? path.join(app.getPath('documents'), 'Haruka Cover Studio') : PROJECT_ROOT, 'outputs')

  backendProcess = spawn(
    python,
    ['-m', 'uvicorn', 'backend.app:app', '--host', '127.0.0.1', '--port', String(port), '--log-level', 'warning'],
    {
      cwd: PROJECT_ROOT,
      env: {
        ...process.env,
        PYTHONIOENCODING: 'utf-8',
        PYTHONUTF8: '1',
        HARUKA_BACKEND_TOKEN: token,
        HARUKA_OUTPUT_ROOT: outputRoot,
        HARUKA_PROJECT_ROOT: PROJECT_ROOT,
        // 显式选择的环境优先；轻量版始终使用外部路径，不改写外部 venv。
        HARUKA_RVC_APP_ROOT: settings.rvcAppRoot,
        HARUKA_INFERENCE_PYTHON: settings.inferencePython,
        HARUKA_FFMPEG: settings.ffmpeg,
      },
      windowsHide: true,
    }
  )

  backendProcess.stdout.on('data', (chunk) => process.stdout.write(`[backend] ${chunk}`))
  backendProcess.stderr.on('data', (chunk) => process.stderr.write(`[backend] ${chunk}`))
  const startedProcess = backendProcess
  backendProcess.on('exit', (code) => {
    console.error(`[backend] 进程退出，退出码 ${code}`)
    if (backendProcess === startedProcess) { backendProcess = null; backendInfo = null }
  })

  const health = await waitForHealth(baseUrl, token)
  backendInfo = { baseUrl, token, outputRoot, python, health }
  return backendInfo
}

async function stopBackend() {
  if (!backendProcess) return
  const pid = backendProcess.pid
  backendProcess = null
  backendInfo = null
  try {
    // Windows 下必须结束整个进程树，避免 uvicorn 子进程残留
    await new Promise((resolve) => {
      const killer = spawn('taskkill', ['/pid', String(pid), '/T', '/F'], { windowsHide: true })
      killer.once('exit', resolve)
      killer.once('error', resolve)
    })
  } catch {
    // 进程可能已自行退出
  }
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 860,
    minWidth: 1024,
    minHeight: 700,
    backgroundColor: '#f7f8f5',
    title: 'Haruka Cover Studio',
    // 窗口/任务栏图标；打包后 exe 图标由 electron-builder 单独注入
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })

  if (IS_DEV) {
    mainWindow.loadURL(DEV_URL)
  } else {
    // 生产模式下前端位于 app.asar/dist，必须相对 __dirname 解析，
    // 不能使用 PROJECT_ROOT（打包后它是 resources 目录，页面不在那里）
    mainWindow.loadFile(path.join(__dirname, '..', 'dist', 'index.html'))
  }

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

ipcMain.handle('backend-info', async () => {
  await startupPromise
  if (!backendInfo) throw new Error(startupError || '请先配置运行环境。')
  return {
    baseUrl: backendInfo.baseUrl,
    token: backendInfo.token,
    outputRoot: backendInfo.outputRoot,
    health: backendInfo.health,
  }
})

ipcMain.handle('restart-backend', async () => {
  await ensureIdle()
  await stopBackend()
  return startBackend()
})

async function ensureIdle() {
  if (!backendInfo) return
  const response = await fetch(`${backendInfo.baseUrl}/api/jobs`, { headers: { 'X-Haruka-Token': backendInfo.token }, signal: AbortSignal.timeout(5000) })
  if (!response.ok) throw new Error('无法确认任务状态，请稍后重试。')
  const jobs = await response.json()
  if (jobs.some(job => ['queued', 'running'].includes(job.status))) throw new Error('请等待当前转换完成或取消任务后，再切换运行环境。')
}

ipcMain.handle('runtime-settings', () => ({ settings: effectiveRuntime(), lightweight: LIGHTWEIGHT, configPath: settingsFile() }))
ipcMain.handle('runtime-discover', () => {
  const roots = [PROJECT_ROOT, path.dirname(PROJECT_ROOT), app.getPath('documents'), app.getPath('downloads'), app.getPath('desktop'), process.env.ProgramFiles, process.env['ProgramFiles(x86)'], path.join(process.env.LOCALAPPDATA || app.getPath('home'), 'Programs'), ...(process.env.PATH || '').split(path.delimiter)]
  // 盘符根目录只查看常见软件文件夹，不递归扫描整盘。
  for (let code = 67; code <= 90; code++) { const drive = `${String.fromCharCode(code)}:\\`; if (fs.existsSync(drive)) roots.push(drive) }
  return discoverRuntime(roots, { checkBackend: python => probePython(python, 'backend', '', BACKEND_DIR, path.join(app.getPath('userData'), 'runtime-check')) })
})
ipcMain.handle('runtime-check', (_event, settings) => validateRuntime(settings, BACKEND_DIR, path.join(app.getPath('userData'), 'runtime-check')))
ipcMain.handle('runtime-apply', async (_event, settings) => {
  if (applyingRuntime) throw new Error('正在应用运行环境，请稍候。')
  applyingRuntime = true
  try {
    await startupPromise
    await ensureIdle()
    const normalized = resolveRuntime(settings, {}, PROJECT_ROOT, true)
    const report = await validateRuntime(normalized, BACKEND_DIR, path.join(app.getPath('userData'), 'runtime-check'))
    if (!report.ok) return { ...report, backend: null }
    const previous = effectiveRuntime()
    const wasRunning = !!backendInfo
    await stopBackend()
    try {
      const backend = await startBackend(normalized)
      const bundleRoot = resolveRuntime({}, {}, PROJECT_ROOT, true).rvcAppRoot
      // 随包代码保存为标记，移动解压目录后不会继续引用旧的绝对路径。
      const persisted = { ...normalized, rvcAppRoot: bundleRoot && path.resolve(bundleRoot).toLowerCase() === path.resolve(normalized.rvcAppRoot).toLowerCase() ? '@bundled' : normalized.rvcAppRoot }
      writeSettings(settingsFile(), persisted)
      runtimeSettings = persisted
      startupError = ''
      return { ...report, backend }
    } catch (error) {
      await stopBackend()
      if (wasRunning) { try { await startBackend(previous) } catch { /* 原环境也失败时，由设置页继续恢复。 */ } }
      throw error
    }
  } finally { applyingRuntime = false }
})

ipcMain.handle('choose-directory', async (_event, title) => {
  const result = await dialog.showOpenDialog(mainWindow, { title: title || '选择目录', properties: ['openDirectory'] })
  return result.canceled ? null : result.filePaths[0]
})

ipcMain.handle('choose-file', async (_event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options?.title || '选择文件',
    properties: ['openFile'],
    filters: options?.filters || [{ name: '音频文件', extensions: ['wav', 'flac', 'mp3', 'm4a'] }],
  })
  return result.canceled ? null : result.filePaths[0]
})

// 批量页一次选择多首音频，仍只返回路径，不复制或改写原文件。
ipcMain.handle('choose-files', async (_event, options) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: options?.title || '选择多首干声', properties: ['openFile', 'multiSelections'],
    filters: options?.filters || [{ name: '音频文件', extensions: ['wav', 'flac', 'mp3', 'ogg'] }],
  })
  return result.canceled ? [] : result.filePaths
})

ipcMain.handle('reveal-in-folder', async (_event, targetPath) => {
  if (!targetPath) return false
  shell.showItemInFolder(targetPath)
  return true
})

ipcMain.handle('open-dir', async (_event, dirPath) => {
  if (!dirPath) return false
  const error = await shell.openPath(dirPath)
  return error === ''
})

// 导出通过原生另存为对话框选择位置，取消时不写入文件。
ipcMain.handle('save-audio', async (_event, name, bytes) => {
  const extension = path.extname(name).slice(1).toLowerCase()
  if (!['wav', 'flac'].includes(extension)) throw new Error('不支持的导出格式')
  const result = await dialog.showSaveDialog(mainWindow, {
    title: '导出音频', defaultPath: path.basename(name),
    filters: [{ name: extension.toUpperCase(), extensions: [extension] }],
  })
  if (result.canceled || !result.filePath) return null
  await fs.promises.writeFile(result.filePath, Buffer.from(bytes))
  return result.filePath
})

app.whenReady().then(() => {
  ensureRuntimePortable()
  // 先显示设置界面，即使对方尚未安装 Python 也能选择环境。
  startupPromise = (async () => {
    try {
      runtimeSettings = readSettings(settingsFile())
      if (LIGHTWEIGHT) {
        const settings = effectiveRuntime()
        if (!settings.inferencePython) throw new Error('轻量版首次使用，请选择已有运行环境。')
        const report = await validateRuntime(settings, BACKEND_DIR, path.join(app.getPath('userData'), 'runtime-check'))
        if (!report.ok) throw new Error(report.items.filter(item => !item.ok).map(item => `${item.name}：${item.detail}`).join('\n'))
      }
      await startBackend()
    } catch (error) { startupError = String(error.message || error); await stopBackend() }
  })()
  createWindow()

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  stopBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => stopBackend())
