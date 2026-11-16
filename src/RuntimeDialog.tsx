import { useEffect, useState } from 'react'
import type { BackendInfo, RuntimeSettings, RuntimeReport, RuntimeDiscovery } from './types'

type Props = { connected: boolean; onClose: () => void; onApplied: (info: BackendInfo) => void; onDiagnostics: () => void }
const FIELDS: { key: keyof RuntimeSettings; label: string; hint: string }[] = [
  { key: 'inferencePython', label: 'RVC 推理 Python', hint: '选择现有 RVC 环境中的 python.exe，例如 runtime/python.exe 或 .venv/Scripts/python.exe。' },
  { key: 'rvcAppRoot', label: 'RVC 代码目录', hint: '选择包含 infer/cli.py 与 assets 的目录。e400、v6e 需要与模型配套的代码。' },
  { key: 'ffmpeg', label: 'FFmpeg', hint: '选择电脑上已有的 ffmpeg.exe。' },
  { key: 'backendPython', label: '后端 Python（可选）', hint: '留空时使用推理 Python；需要 FastAPI、Uvicorn、Pydantic 2、NumPy、SciPy、SoundFile。也可选择另一个兼容环境。' },
]

export default function RuntimeDialog({ connected, onClose, onApplied, onDiagnostics }: Props) {
  const [settings, setSettings] = useState<RuntimeSettings>({ backendPython: '', inferencePython: '', rvcAppRoot: '', ffmpeg: '' })
  const [report, setReport] = useState<RuntimeReport | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [discovering, setDiscovering] = useState(false)
  const [discovery, setDiscovery] = useState<RuntimeDiscovery | null>(null)
  const discover = async () => {
    setDiscovering(true); setError('')
    try {
      const result = await window.haruka.discoverRuntime()
      setDiscovery(result)
      // 只补充空白项，已有保存配置或用户手动选择的路径不会被搜索覆盖。
      setSettings(current => Object.fromEntries(Object.entries(current).map(([key, value]) => [key, value || result.settings[key as keyof RuntimeSettings]])) as RuntimeSettings)
      setReport(null)
    } catch (reason) { setError(String(reason)) } finally { setDiscovering(false) }
  }
  useEffect(() => {
    window.haruka.runtimeSettings().then(async data => { setSettings(data.settings); if (!data.settings.inferencePython) await discover() }).catch(reason => setError(String(reason))).finally(() => setLoading(false))
  }, [])
  const update = (key: keyof RuntimeSettings, value: string) => { setSettings(current => ({ ...current, [key]: value })); setReport(null) }
  const choose = async (key: keyof RuntimeSettings) => {
    try {
      const selected = key === 'rvcAppRoot' ? await window.haruka.chooseDirectory('选择配套 RVC 代码目录') : await window.haruka.chooseFile({ title: key === 'ffmpeg' ? '选择 FFmpeg' : '选择 Python 解释器', filters: [{ name: '可执行程序', extensions: ['exe'] }] })
      if (selected) update(key, selected)
    } catch (reason) { setError(String(reason)) }
  }
  const check = async (apply: boolean) => {
    setBusy(true); setError(''); setReport(null)
    try {
      const result = await (apply ? window.haruka.applyRuntime(settings) : window.haruka.checkRuntime(settings))
      setReport(result)
      if (result.ok && result.backend) onApplied(result.backend)
    } catch (reason) { setError(String((reason as Error)?.message || reason)) } finally { setBusy(false) }
  }
  return <div className="modal-mask"><div className="modal wide">
    <header className="modal-head"><h2>运行环境设置</h2><button className="close" disabled={busy || discovering} onClick={onClose} aria-label="关闭">×</button></header>
    <div className="modal-body">
      <p className="input-note">复用这台电脑已有的环境。只保存路径和检查兼容性，不自动安装或升级依赖。</p>
      <p className="input-note" role="status">{discovering ? '正在搜索常见安装目录…' : discovery ? `找到 ${discovery.pythons.length} 个 Python、${discovery.rvcApps.length} 个 RVC 目录、${discovery.ffmpegs.length} 个 FFmpeg。候选路径已填入，请检查后使用。${discovery.limited ? '搜索已达到目录上限，可手动补充。' : ''}` : '点击自动查找，可填入电脑上已有的候选环境。'}</p>
      {FIELDS.map(({ key, label, hint }) => <div className="field runtime-field" key={key}><label htmlFor={`runtime-${key}`}>{label}</label><div className="file-row"><input id={`runtime-${key}`} list={`candidates-${key}`} value={settings[key]} disabled={busy || loading || discovering} onChange={event => update(key, event.target.value)} placeholder={key === 'backendPython' ? '与推理 Python 相同' : '选择已有路径'} /><datalist id={`candidates-${key}`}>{(key === 'rvcAppRoot' ? discovery?.rvcApps.map(item => item.path) : key === 'ffmpeg' ? discovery?.ffmpegs : discovery?.pythons.map(item => item.path))?.map(value => <option key={value} value={value} />)}</datalist><button disabled={busy || loading || discovering} onClick={() => choose(key)}>选择…</button></div><p className="input-note">{hint}</p></div>)}
      {busy && <p className="muted" role="status">正在检查环境，首次加载 PyTorch 可能需要一两分钟…</p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      {report && <div role="status">{report.items.map(item => <div className="diag-row" key={item.name}><span className={`dot ${item.ok ? 'ok' : 'bad'}`} /><div><strong>{item.name}</strong><p>{item.detail}</p></div></div>)}<p className="input-note">{report.ok ? '环境检查通过；具体声线的代码匹配和效果仍需短音频试转确认。' : '请按提示重新选择环境或补齐文件，再检查。'}</p></div>}
    </div>
    <footer className="modal-foot">{connected && <button disabled={busy || discovering} onClick={onDiagnostics}>模型与任务诊断</button>}<button disabled={busy || loading || discovering} onClick={discover}>{discovering ? '查找中…' : '自动查找'}</button><button disabled={busy || loading || discovering} onClick={() => check(false)}>仅检查</button><button className="primary" disabled={busy || loading || discovering} onClick={() => check(true)}>{busy ? '检查中…' : '检查并使用'}</button></footer>
  </div></div>
}
