import { useState } from 'react'
import type { CoverRequest, DeviceOption, Preset } from './types'

type Row = { id: string; path: string; backing: string; presets: string[]; pitch: number }
const shortName = (path: string) => path.split(/[\\/]/).pop() || path
export default function BatchBuilder({ presets, device, devices, detail, onDevice, onSubmit }: {
  presets: Preset[]; device: string; devices: DeviceOption[]; detail: string; onDevice: (id: string) => void; onSubmit: (items: CoverRequest[]) => Promise<void>
}) {
  const [rows, setRows] = useState<Row[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const available = presets.filter(preset => preset.model_exists !== false)
  const count = rows.reduce((total, row) => total + row.presets.length, 0)
  const add = (paths: string[]) => setRows(current => [...current, ...paths.filter(path => /\.(wav|flac|mp3|ogg)$/i.test(path)).map(path => ({ id: crypto.randomUUID(), path, backing: '', presets: available[0] ? [available[0].id] : [], pitch: 0 }))])
  const patch = (id: string, value: Partial<Row>) => setRows(current => current.map(row => row.id === id ? { ...row, ...value } : row))
  const pick = async () => { try { add(await window.haruka.chooseFiles({ title: '选择多首干声', filters: [{ name: '音频', extensions: ['wav', 'flac', 'mp3', 'ogg'] }] })) } catch (reason) { setError(String(reason)) } }
  const backing = async (id: string) => { try { const path = await window.haruka.chooseFile({ title: '为这首歌选择伴奏', filters: [{ name: '音频', extensions: ['wav', 'flac', 'mp3', 'ogg'] }] }); if (path) patch(id, { backing: path }) } catch (reason) { setError(String(reason)) } }
  const submit = async () => {
    if (busy) return
    setError('')
    if (!rows.length || rows.some(row => !row.presets.length)) { setError('请添加干声，并为每首歌至少选择一个模型。'); return }
    if (count > 100) { setError('一次最多加入 100 个任务，请分批提交。'); return }
    setBusy(true)
    try {
      // 按歌曲与模型展开为独立快照；不按文件名猜测伴奏，避免误配音轨。
      await onSubmit(rows.flatMap(row => row.presets.map(id => ({ kind: 'cover', vocal_path: row.path, instrumental_path: row.backing || null, preset_id: id, song_title: shortName(row.path).replace(/\.[^.]+$/, ''), pitch_semitones: row.pitch, device }))))
      setRows([])
    } catch (reason) { setError(String((reason as Error).message || reason)) } finally { setBusy(false) }
  }
  return <section className="panel batch-builder">
    <div className="section-head"><h2>批量制作</h2><span className="muted">每首歌可选多个模型</span></div>
    <button className="drop-zone batch-drop" disabled={busy} onClick={pick} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!busy) add(Array.from(event.dataTransfer.files).map(file => window.haruka.filePath(file)).filter(Boolean)) }}>拖入多首干声，或点击选择</button>
    <div className="field device-field"><label htmlFor="batch-device">本批任务运行设备</label><select id="batch-device" value={device} disabled={busy} onChange={event => onDevice(event.target.value)}>{devices.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select><p className="input-note">{detail}</p></div>
    {rows.map((row, index) => <div className="batch-row" key={row.id}>
      <div className="batch-row-head"><strong>{index + 1}. {shortName(row.path)}</strong><button className="ghost small" disabled={busy} onClick={() => setRows(current => current.filter(item => item.id !== row.id))}>移出列表</button></div>
      <div className="batch-row-fields"><button disabled={busy} title={row.backing || undefined} onClick={() => backing(row.id)} onDragOver={event => event.preventDefault()} onDrop={event => { event.preventDefault(); if (!busy && event.dataTransfer.files[0]) patch(row.id, { backing: window.haruka.filePath(event.dataTransfer.files[0]) }) }}>{row.backing ? shortName(row.backing) : '添加 / 拖入伴奏（可选）'}</button>
        {row.backing && <button className="ghost small" disabled={busy} onClick={() => patch(row.id, { backing: '' })}>清除伴奏</button>}
        <label>升降调<input aria-label={`${shortName(row.path)} 升降调`} type="number" min="-12" max="12" step="1" value={row.pitch} disabled={busy} onChange={event => patch(row.id, { pitch: Number(event.target.value) })} /></label>
      </div>
      <div className="model-checks">{available.map(preset => <label key={preset.id}><input type="checkbox" disabled={busy} checked={row.presets.includes(preset.id)} onChange={event => patch(row.id, { presets: event.target.checked ? [...row.presets, preset.id] : row.presets.filter(id => id !== preset.id) })} />{preset.display_name}</label>)}</div>
    </div>)}
    {error && <p className="inline-error" role="alert">{error}</p>}
    <div className="batch-submit"><span className="muted">{rows.length} 首歌 · {count} 个转换任务</span><button className="primary compact" disabled={busy || !count} onClick={submit}>{busy ? '正在检查…' : `加入队列（${count}）`}</button></div>
  </section>
}
