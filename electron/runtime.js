'use strict'

const fs = require('node:fs')
const path = require('node:path')
const { execFile } = require('node:child_process')
const { promisify } = require('node:util')
const execute = promisify(execFile)
const KEYS = ['backendPython', 'inferencePython', 'rvcAppRoot', 'ffmpeg']

function readSettings(file) {
  if (!fs.existsSync(file)) return {}
  try {
    const value = JSON.parse(fs.readFileSync(file, 'utf8'))
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Invalid object')
    return Object.fromEntries(KEYS.map(key => [key, typeof value[key] === 'string' ? value[key] : '']))
  } catch { throw new Error('运行环境配置损坏，请重新选择并保存。') }
}

function writeSettings(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  // 只持久化用户选择的路径，令牌和进程环境不写入配置。
  const data = Object.fromEntries(KEYS.map(key => [key, String(value[key] || '').trim()]))
  fs.writeFileSync(`${file}.tmp`, JSON.stringify(data, null, 2), 'utf8')
  fs.renameSync(`${file}.tmp`, file)
}

function resolveRuntime(saved, env, root, lightweight) {
  const bundled = name => path.join(root, 'runtime', name, 'Scripts', 'python.exe')
  const inferencePython = saved.inferencePython || env.HARUKA_INFERENCE_PYTHON || (lightweight ? '' : bundled('python-rvc'))
  const selectedApp = saved.rvcAppRoot === '@bundled' ? bundledAppRoot(root) : saved.rvcAppRoot
  return {
    backendPython: saved.backendPython || env.HARUKA_BACKEND_PYTHON || (lightweight ? inferencePython : bundled('python-backend')),
    inferencePython,
    rvcAppRoot: selectedApp || env.HARUKA_RVC_APP_ROOT || (lightweight ? bundledAppRoot(root) : path.join(root, 'runtime', 'rvc-app')),
    ffmpeg: saved.ffmpeg || env.HARUKA_FFMPEG || (lightweight ? '' : path.join(root, 'runtime', 'ffmpeg', 'ffmpeg.exe')),
  }
}

function bundledAppRoot(root) {
  const bundle = path.resolve(root, 'model-bundle')
  const file = path.join(bundle, 'default-runtime.json')
  if (!fs.existsSync(file)) return ''
  const relative = JSON.parse(fs.readFileSync(file, 'utf8')).rvc_app_root
  const target = path.resolve(bundle, relative)
  if (!target.startsWith(bundle + path.sep) || !fs.existsSync(path.join(target, 'infer', 'cli.py'))) throw new Error('随包推理代码缺失，请完整解压模型包。')
  return target
}

async function probePython(python, role, appRoot, backendDir, cacheDir) {
  if (!python || !fs.existsSync(python) || !fs.statSync(python).isFile()) throw new Error('请选择有效的 Python 解释器文件。')
  const { stdout } = await execute(python, ['-B', path.join(backendDir, 'runtime_probe.py'), role, appRoot || ''], {
    windowsHide: true, timeout: role === 'backend' ? 15000 : 120000, maxBuffer: 1024 * 1024,
    env: { ...process.env, PYTHONUTF8: '1', PYTHONIOENCODING: 'utf-8', HARUKA_RUNTIME_CACHE: cacheDir },
  })
  const line = stdout.split(/\r?\n/).findLast(value => value.startsWith('HARUKA_PROBE_JSON='))
  if (!line) throw new Error('环境检查未返回结果，请确认选择的是 Python 解释器。')
  const result = JSON.parse(line.slice('HARUKA_PROBE_JSON='.length))
  if (!result.ok) throw new Error(result.detail)
  return result.detail
}

async function validateRuntime(settings, backendDir, cacheDir = path.join(backendDir, '..', '.cache', 'runtime-check')) {
  const items = []
  const check = async (name, operation) => {
    try { items.push({ name, ok: true, detail: await operation() }) }
    catch (error) { items.push({ name, ok: false, detail: String(error.message || error).slice(-2500) }) }
  }
  const requireFile = (file, label) => {
    if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) throw new Error(`请选择有效的${label}文件。`)
  }
  const probe = (python, role) => probePython(python, role, settings.rvcAppRoot, backendDir, cacheDir)
  await check('后端 Python', () => probe(settings.backendPython || settings.inferencePython, 'backend'))
  await check('RVC 推理 Python', () => probe(settings.inferencePython, 'inference'))
  await check('RVC 代码与基础模型', async () => {
    for (const file of ['infer/cli.py', 'infer/vc/modules.py', 'infer/vc/pipeline.py', 'assets/hubert_base/config.json', 'assets/hubert_base/preprocessor_config.json', 'assets/rmvpe/rmvpe.pt']) {
      if (!settings.rvcAppRoot) throw new Error('请选择与声线模型配套的 RVC 代码目录。')
      requireFile(path.join(settings.rvcAppRoot, file), ` RVC 文件 ${file}`)
    }
    const hubert = path.join(settings.rvcAppRoot, 'assets', 'hubert_base')
    if (!['model.safetensors', 'pytorch_model.bin'].some(file => fs.existsSync(path.join(hubert, file)))) throw new Error('缺少 assets/hubert_base 中的 HuBERT 权重。')
    return settings.rvcAppRoot
  })
  await check('FFmpeg', async () => {
    requireFile(settings.ffmpeg, ' FFmpeg')
    const { stdout } = await execute(settings.ffmpeg, ['-version'], { windowsHide: true, timeout: 15000, maxBuffer: 1024 * 1024 })
    if (!stdout.startsWith('ffmpeg version')) throw new Error('选择的程序不是可用的 FFmpeg。')
    return stdout.split(/\r?\n/)[0]
  })
  return { ok: items.every(item => item.ok), items }
}

module.exports = { readSettings, writeSettings, resolveRuntime, validateRuntime, probePython }
