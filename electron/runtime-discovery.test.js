const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const os = require('node:os')
const { discoverRuntime } = require('./runtime-discovery')

test('discovers a compatible layout without traversing large assets', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(),'haruka-discovery-'))
  const files = ['VoiceTool/runtime/python.exe','VoiceTool/runtime/Lib/site-packages/torch/__init__.py','VoiceTool/runtime/Lib/site-packages/fastapi/__init__.py','VoiceTool/ffmpeg/bin/ffmpeg.exe','VoiceTool/app/infer/cli.py','VoiceTool/app/assets/hubert_base/config.json','VoiceTool/app/assets/hubert_base/pytorch_model.bin','VoiceTool/app/assets/rmvpe/rmvpe.pt','unrelated/python.exe']
  for(const file of files) { fs.mkdirSync(path.dirname(path.join(root,file)),{recursive:true});fs.writeFileSync(path.join(root,file),'fixture') }
  const result = await discoverRuntime([root])
  assert.equal(result.settings.inferencePython,path.join(root,'VoiceTool/runtime/python.exe'))
  assert.equal(result.settings.backendPython,result.settings.inferencePython)
  assert.equal(result.settings.rvcAppRoot,path.join(root,'VoiceTool/app'))
  assert.equal(result.settings.ffmpeg,path.join(root,'VoiceTool/ffmpeg/bin/ffmpeg.exe'))
  assert.equal(result.pythons.some(item=>item.path.includes('unrelated')),false)
  const incompatible = await discoverRuntime([root], { checkBackend: async () => { throw new Error('Incompatible dependency versions') } })
  assert.equal(incompatible.settings.backendPython, '')
  const limited = await discoverRuntime([root],{maxDirectories:1})
  assert.equal(limited.limited,true)
  // 只删除本测试显式创建的文件，再按深度移除已空的目录。
  for(const file of files) fs.unlinkSync(path.join(root,file))
  const dirs=new Set(files.flatMap(file=>{const values=[];let p=path.dirname(path.join(root,file));while(p!==root){values.push(p);p=path.dirname(p)}return values}))
  for(const directory of [...dirs].sort((a,b)=>b.length-a.length)) fs.rmdirSync(directory)
  fs.rmdirSync(root)
})
