const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { resolveRuntime, readSettings, writeSettings, validateRuntime } = require('./runtime')

test('lightweight runtime does not fall back to bundled or machine paths', () => {
  assert.deepEqual(resolveRuntime({}, {}, '/bundle', true), { backendPython: '', inferencePython: '', rvcAppRoot: '', ffmpeg: '' })
})
test('saved paths override inherited environment and bundle', () => {
  const saved = { backendPython: 'backend', inferencePython: 'infer', rvcAppRoot: 'app', ffmpeg: 'ffmpeg' }
  assert.deepEqual(resolveRuntime(saved, { HARUKA_INFERENCE_PYTHON: 'wrong' }, '/bundle', false), saved)
})
test('one selected Python can serve both roles', () => {
  const value = resolveRuntime({ inferencePython: 'python' }, {}, '/bundle', true)
  assert.equal(value.backendPython, 'python')
})
test('full package retains its default runtime', () => {
  assert.equal(resolveRuntime({}, {}, '/bundle', false).inferencePython, path.join('/bundle', 'runtime', 'python-rvc', 'Scripts', 'python.exe'))
})
test('settings persist Unicode paths without unknown fields', () => {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'haruka-runtime-'))
  const file = path.join(directory, 'settings.json')
  try {
    const settings = { backendPython: 'D:\\已有环境\\python.exe', inferencePython: '', rvcAppRoot: '', ffmpeg: '' }
    writeSettings(file, { ...settings, token: 'do-not-save' })
    assert.deepEqual(readSettings(file), settings)
    assert.equal(fs.readFileSync(file, 'utf8').includes('do-not-save'), false)
    fs.writeFileSync(file, '{broken')
    assert.throws(() => readSettings(file), /配置/)
  } finally { fs.rmSync(file); fs.rmdirSync(directory) }
})
test('missing dependencies produce actionable errors before launch', async () => {
  const result = await validateRuntime({ backendPython: '', inferencePython: '', rvcAppRoot: '', ffmpeg: '' }, __dirname)
  assert.equal(result.ok, false)
  assert.equal(result.items.length, 4)
  assert.ok(result.items.every(item => !item.ok && item.detail))
})

test('model edition finds its bundled app after relocation without an external runtime', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'haruka-bundled-'))
  const bundle = path.join(root, 'model-bundle')
  const app = path.join(bundle, 'apps', 'e400')
  fs.mkdirSync(path.join(app, 'infer'), {recursive:true})
  fs.writeFileSync(path.join(app, 'infer', 'cli.py'), '# fixture')
  fs.writeFileSync(path.join(bundle, 'default-runtime.json'), JSON.stringify({rvc_app_root:'apps/e400'}))
  try {
    const resolved = resolveRuntime({}, {}, root, true)
    assert.equal(resolved.rvcAppRoot, app)
    assert.equal(resolved.inferencePython, '')
    assert.equal(resolveRuntime({rvcAppRoot:'@bundled'}, {}, root, true).rvcAppRoot, app)
    assert.equal(resolveRuntime({rvcAppRoot:'chosen'}, {}, root, true).rvcAppRoot, 'chosen')
  } finally {
    fs.unlinkSync(path.join(app, 'infer', 'cli.py'))
    fs.unlinkSync(path.join(bundle, 'default-runtime.json'))
    for(const directory of [path.join(app,'infer'),app,path.dirname(app),bundle,root]) fs.rmdirSync(directory)
  }
})
