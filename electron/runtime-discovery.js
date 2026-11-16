'use strict'

const fs = require('node:fs/promises')
const path = require('node:path')
const RELEVANT = /rvc|haruka|voice|audio|webui|ffmpeg|python|conda|pinokio|tools|语音|模型|音频|整合包/i
const LAYOUT = /^(runtime|resources|app|backend|env|envs|venv|\.venv|scripts|bin|local_deployments)$/i
const SKIP = /^(node_modules|lib|libs|include|share|assets|models?|model-registry|datasets?|data|outputs?|logs?|tests?|\.git|\.cache|cache|\.build|win-unpacked|windows|programdata|\$recycle\.bin|system volume information)$|^release(?:-|$)|-build$/i
const exists = async file => { try { return (await fs.stat(file)).isFile() } catch { return false } }

async function discoverRuntime(roots, { maxDirectories = 1800, maxDepth = 6, checkBackend } = {}) {
  const queue = [...new Set(roots.filter(Boolean).map(root => path.resolve(root)))].map(directory => ({ directory, depth: 0, relevant: false }))
  const visited = new Set(), pythonPaths = new Set(), pythons = [], rvcApps = [], ffmpegs = []
  const addPython = async python => {
    if (pythonPaths.has(python.toLowerCase()) || !(await exists(python))) return
    pythonPaths.add(python.toLowerCase())
    const directory = path.dirname(python)
    const base = path.basename(directory).toLowerCase() === 'scripts' ? path.dirname(directory) : directory
    const site = path.join(base, 'Lib', 'site-packages')
    pythons.push({ path: python, torch: await exists(path.join(site, 'torch', '__init__.py')), backend: await exists(path.join(site, 'fastapi', '__init__.py')) })
  }
  let limited = false
  while (queue.length && visited.size < maxDirectories) {
    const { directory, depth, relevant } = queue.shift()
    const key = directory.toLowerCase()
    if (visited.has(key) || /windowsapps/i.test(directory)) continue
    visited.add(key)
    let entries
    try { entries = await fs.readdir(directory, { withFileTypes: true }) } catch { continue }
    const names = new Set(entries.map(entry => entry.name.toLowerCase()))
    if (names.has('python.exe')) await addPython(path.join(directory, 'python.exe'))
    // 直接检查整合包的固定布局，避免较深的 Scripts 目录因搜索预算被漏掉。
    for (const [name, relatives] of Object.entries({
      runtime: ['runtime/python.exe', 'runtime/python-rvc/Scripts/python.exe', 'runtime/python-backend/Scripts/python.exe'],
      resources: ['resources/runtime/python-rvc/Scripts/python.exe', 'resources/runtime/python-backend/Scripts/python.exe'],
      '.venv': ['.venv/Scripts/python.exe'], venv: ['venv/Scripts/python.exe'], env: ['env/python.exe', 'env/Scripts/python.exe'],
    })) {
      if (names.has(name)) for (const relative of relatives) await addPython(path.join(directory, relative))
    }
    if (names.has('ffmpeg.exe')) ffmpegs.push(path.join(directory, 'ffmpeg.exe'))
    if (names.has('infer') && await exists(path.join(directory, 'infer', 'cli.py'))) {
      const hubert = path.join(directory, 'assets', 'hubert_base')
      const complete = await exists(path.join(hubert, 'config.json')) && (await exists(path.join(hubert, 'pytorch_model.bin')) || await exists(path.join(hubert, 'model.safetensors'))) && await exists(path.join(directory, 'assets', 'rmvpe', 'rmvpe.pt'))
      rvcApps.push({ path: directory, complete })
    }
    if (depth >= maxDepth) continue
    // 只进入常见软件目录；大模型、数据和 Python 包目录不递归扫描。
    for (const entry of entries.filter(entry => entry.isDirectory() && !entry.isSymbolicLink()).sort((a, b) => a.name.localeCompare(b.name))) {
      if (SKIP.test(entry.name)) continue
      const match = RELEVANT.test(entry.name) || LAYOUT.test(entry.name)
      if (relevant || match) queue.push({ directory: path.join(directory, entry.name), depth: depth + 1, relevant: relevant || match })
    }
  }
  limited = queue.length > 0
  pythons.sort((a, b) => Number(b.torch) - Number(a.torch) || Number(/rvc|haruka/i.test(b.path)) - Number(/rvc|haruka/i.test(a.path)) || Number(b.backend) - Number(a.backend) || a.path.localeCompare(b.path))
  rvcApps.sort((a, b) => Number(b.complete) - Number(a.complete) || a.path.localeCompare(b.path))
  const inference = pythons.find(item => item.torch)
  const backends = pythons.filter(item => item.backend).sort((a, b) => Number(a.torch) - Number(b.torch))
  let backend = backends[0]
  if (checkBackend) {
    backend = undefined
    // 后端依赖常与旧 RVC 环境冲突，实际导入检查后再填入，最多尝试五个候选。
    for (const candidate of backends.slice(0, 5)) {
      try { await checkBackend(candidate.path); backend = candidate; break } catch { /* 保留候选供用户手动选择，但不自动采用失败环境。 */ }
    }
  }
  return {
    settings: { inferencePython: inference?.path || '', backendPython: backend?.path || '', rvcAppRoot: rvcApps.find(item => item.complete)?.path || '', ffmpeg: ffmpegs[0] || '' },
    pythons, rvcApps, ffmpegs, scannedDirectories: visited.size, limited,
  }
}

module.exports = { discoverRuntime }
