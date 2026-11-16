import { useCallback, useEffect, useState } from 'react'
import DiagnosticsDialog from './DiagnosticsDialog'
import ImportModelDialog from './ImportModelDialog'
import RuntimeDialog from './RuntimeDialog'
import WaveformSelector from './WaveformSelector'
import ComparisonPlayer from './ComparisonPlayer'
import QueuePanel from './QueuePanel'
import BatchBuilder from './BatchBuilder'
import type { BackendInfo, CoverRequest, DeviceOption, Job, Preset, PreviewRange } from './types'

const TERMINAL = new Set(['succeeded', 'failed', 'cancelled'])
const STAGES: Record<string, string> = { queued: '排队中', starting: '准备中', probe: '检查输入', loading_runtime: '加载模型', global_condition: '提取音高', converting: '转换声音', resampling: '处理音频', mixing: '伴奏混音', validating: '校验产物', done: '已完成', failed: '失败', cancelled: '已取消' }
const STATUSES: Record<string, string> = { queued: '排队中', running: '执行中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
const shortName = (path: string) => path.split(/[\\/]/).pop() || path

export default function App() {
  const [backend, setBackend] = useState<BackendInfo | null>(null)
  const [backendError, setBackendError] = useState('')
  const [presets, setPresets] = useState<Preset[]>([])
  const [presetId, setPresetId] = useState('')
  const [view, setView] = useState<'cover' | 'models' | 'history' | 'queue'>('cover')
  const [vocalPath, setVocalPath] = useState('')
  const [backingEnabled, setBackingEnabled] = useState(false)
  const [instrumentalPath, setInstrumentalPath] = useState('')
  const [songTitle, setSongTitle] = useState('')
  const [pitch, setPitch] = useState(0)
  const [indexRate, setIndexRate] = useState(0)
  const [protect, setProtect] = useState(0.33)
  const [gain, setGain] = useState(3)
  const [job, setJob] = useState<Job | null>(null)
  const [history, setHistory] = useState<Job[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [audioBusy, setAudioBusy] = useState(false)
  const [audioUrl, setAudioUrl] = useState('')
  const [track, setTrack] = useState('vocal_44k')
  const [format, setFormat] = useState('wav')
  const [showImport, setShowImport] = useState(false)
  const [showDiagnostics, setShowDiagnostics] = useState(false)
  const [showRuntime, setShowRuntime] = useState(false)
  const [preview, setPreview] = useState(false)
  const [range, setRange] = useState<PreviewRange>({ start: 0, end: 20 })
  const [waveReady, setWaveReady] = useState(false)
  const [compareIds, setCompareIds] = useState<string[]>([])
  const [comparisonGroup, setComparisonGroup] = useState('')
  const [device, setDevice] = useState('auto')
  const [devices, setDevices] = useState<DeviceOption[]>([{ id: 'auto', label: '自动选择', kind: 'auto' }, { id: 'cpu', label: 'CPU（兼容模式）', kind: 'cpu' }])
  const [deviceDetail, setDeviceDetail] = useState('正在检测运行设备…')
  const preset = presets.find((item) => item.id === presetId)
  const running = !!job && !TERMINAL.has(job.status)
  // 已提交任务保存独立参数，转换期间允许准备下一首歌。
  const busy = submitting
  const activeJobs = history.filter(item => !TERMINAL.has(item.status))
  const comparisonJobs = history.filter(item => item.request?.group_id === comparisonGroup).slice().reverse()
  const output = job?.artifacts.find((item) => item.kind === track)

  const api = useCallback(async (path: string, init?: RequestInit) => {
    if (!backend) throw new Error('后端尚未就绪')
    const response = await fetch(`${backend.baseUrl}${path}`, { ...init, headers: { 'Content-Type': 'application/json', 'X-Haruka-Token': backend.token, ...init?.headers } })
    if (!response.ok) {
      let detail = `请求失败：${response.status}`
      try { const body = await response.json(); detail = typeof body.detail === 'string' ? body.detail : detail } catch { /* 保留状态码 */ }
      throw new Error(detail)
    }
    return response
  }, [backend])
  const reportError = (reason: unknown) => setError(String((reason as Error)?.message || reason))
  useEffect(() => {
    let cancelled = false
    window.haruka.backendInfo().then((info) => { if (!cancelled) setBackend(info) }).catch((reason) => { if (!cancelled) { setBackendError(String(reason).split('Error: ').pop() || '请配置运行环境。'); setShowRuntime(true) } })
    return () => { cancelled = true }
  }, [])
  const reloadPresets = useCallback(async () => {
    if (!backend) return
    try {
      const list: Preset[] = await (await api('/api/presets')).json()
      setPresets(list)
      setPresetId((current) => list.some((item) => item.id === current) ? current : (list.find((item) => item.id === 'bundled-haruka-v6b1d-e400') || list.find((item) => item.id === 'haruka-v6b1d-e400') || list[0])?.id || '')
    } catch (reason) { reportError(reason) }
  }, [backend, api])
  useEffect(() => { void reloadPresets() }, [reloadPresets])
  // 切换模型时恢复其默认值；界面设置仅写入本次任务，不改模型预设。
  useEffect(() => {
    setIndexRate(Number(preset?.parameters?.index_rate ?? 0))
    setProtect(Number(preset?.parameters?.protect ?? 0.33))
    setGain(Number(preset?.output?.instrumental_boost_db ?? 3))
  }, [preset])
  useEffect(() => {
    if (!running || !job) return
    let cancelled = false
    const timer = setInterval(async () => {
      try { const next = await (await api(`/api/jobs/${job.id}`)).json(); if (!cancelled) setJob(next) } catch { /* 单次失败留待下一轮重试 */ }
    }, 900)
    return () => { cancelled = true; clearInterval(timer) }
  }, [job?.id, running, api])
  const reloadJobs = useCallback(async () => {
    const list: Job[] = await (await api('/api/jobs')).json()
    setHistory(list)
  }, [api])
  useEffect(() => {
    if (!backend) return
    let stopped = false
    const refresh = async () => { try { const list = await (await api('/api/jobs')).json(); if (!stopped) setHistory(list) } catch { /* 后端短暂切换时保留当前列表，下一轮重试。 */ } }
    void refresh()
    const timer = setInterval(refresh, 1200)
    return () => { stopped = true; clearInterval(timer) }
  }, [backend, api])
  useEffect(() => {
    if (!backend) return
    const controller = new AbortController()
    setDeviceDetail('正在检测运行设备…')
    api('/api/devices', { signal: controller.signal }).then(response => response.json()).then(data => {
      if (!controller.signal.aborted) { setDevices(data.devices); setDeviceDetail(data.detail); setDevice(current => data.devices.some((item: DeviceOption) => item.id === current) ? current : 'auto') }
    }).catch(reason => { if (!controller.signal.aborted) setDeviceDetail(`设备检测失败：${String(reason.message || reason)}。可选择 CPU 后试唱验证。`) })
    return () => controller.abort()
  }, [backend, api])
  useEffect(() => () => { if (audioUrl) URL.revokeObjectURL(audioUrl) }, [audioUrl])

  const pickFile = async (setter: (value: string) => void, title: string) => {
    try { const path = await window.haruka.chooseFile({ title, filters: [{ name: '音频', extensions: ['wav', 'flac', 'mp3', 'ogg'] }] }); if (path) setter(path) } catch (reason) { reportError(reason) }
  }
  // 拖入只修改下一次任务的输入，不修改已经排队的任务快照。
  const dropFile = (event: React.DragEvent, setter: (value: string) => void) => {
    event.preventDefault()
    if (busy || !event.dataTransfer.files[0]) return
    try { const path = window.haruka.filePath(event.dataTransfer.files[0]); if (path) setter(path) } catch (reason) { reportError(reason) }
  }
  const submit = async (whole = false, compare = false) => {
    if (busy) return
    setError(''); setMessage('')
    if (!vocalPath || !presetId || (backingEnabled && !instrumentalPath)) { setError('请选择干声、模型，以及启用后的伴奏文件。'); return }
    if (preview && !whole && !waveReady) { setError('请先等待波形读取完成。'); return }
    if (compare && (compareIds.length < 2 || compareIds.length > 8)) { setError('请选择 2～8 个模型进行对比。'); return }
    setSubmitting(true)
    try {
      const request: CoverRequest = { kind: 'cover', vocal_path: vocalPath,
        instrumental_path: backingEnabled ? instrumentalPath : null, preset_id: presetId, song_title: songTitle || null,
        pitch_semitones: pitch, device, vocal_gain_db: gain,
        preview_start: preview && !whole ? range.start : null, preview_end: preview && !whole ? range.end : null }
      if (compare) {
        const data = await (await api('/api/jobs/batch', { method: 'POST', body: JSON.stringify({ group_kind: 'comparison', items: compareIds.map(id => ({ ...request, preset_id: id })) }) })).json()
        setComparisonGroup(data.group_id); setJob(data.jobs[0]); setMessage('多个模型已加入队列，将依次转换。')
      } else {
        const data = await (await api('/api/jobs', { method: 'POST', body: JSON.stringify({ ...request, index_rate: indexRate, protect }) })).json()
        setJob(data.job); setMessage('任务已加入队列。')
      }
      setAudioUrl(''); setTrack('vocal_44k'); await reloadJobs()
    } catch (reason) { reportError(reason) } finally { setSubmitting(false) }
  }
  const selectTrack = (kind: string) => { setTrack(kind); setAudioUrl(''); setMessage('') }
  const useComparison = async (selected: Job) => {
    if (busy || !selected.request) return
    setSubmitting(true); setError('')
    try {
      // 沿用已试听任务的音源和参数，不读取可能已被改成另一首歌的表单。
      const request = { ...selected.request, preview_start: null, preview_end: null }
      const data = await (await api('/api/jobs', { method: 'POST', body: JSON.stringify(request) })).json()
      setJob(data.job); setAudioUrl(''); setTrack('vocal_44k')
      setMessage('已用该模型和试听时的音源、参数加入整首转换队列。')
      await reloadJobs()
    } catch (reason) { reportError(reason) } finally { setSubmitting(false) }
  }
  const play = async () => {
    if (!job || audioBusy || (track !== 'source' && !output)) return
    setAudioBusy(true); setError('')
    try {
      const route = track === 'source' ? `/api/jobs/${job.id}/source` : `/api/jobs/${job.id}/artifacts/${encodeURIComponent(output!.name)}`
      setAudioUrl(URL.createObjectURL(await (await api(route)).blob()))
    } catch (reason) { reportError(reason) } finally { setAudioBusy(false) }
  }
  const exportAudio = async () => {
    if (!job || !output || audioBusy) return
    setAudioBusy(true); setError(''); setMessage('')
    try {
      const response = await api(`/api/jobs/${job.id}/artifacts/${encodeURIComponent(output.name)}?format=${format}`)
      const saved = await window.haruka.saveAudio(output.name.replace(/\.wav$/i, `.${format}`), await response.arrayBuffer())
      if (saved) setMessage(`已导出：${saved}`)
    } catch (reason) { reportError(reason) } finally { setAudioBusy(false) }
  }
  const openHistory = async (id: string) => {
    try { const data = await (await api(`/api/jobs/${id}`)).json(); setJob(data); if (data.request?.group_kind === 'comparison') setComparisonGroup(data.request.group_id); setAudioUrl(''); setTrack('vocal_44k'); setView('cover') } catch (reason) { reportError(reason) }
  }
  const cancelJob = async (id: string) => { try { const data = await (await api(`/api/jobs/${id}/cancel`, { method: 'POST' })).json(); if (job?.id === id) setJob(data); await reloadJobs() } catch (reason) { reportError(reason) } }
  const retryJob = async (id: string) => { try { const data = await (await api(`/api/jobs/${id}/retry`, { method: 'POST' })).json(); setJob(data.job); await reloadJobs() } catch (reason) { reportError(reason) } }
  const submitBatch = async (items: CoverRequest[]) => {
    await api('/api/jobs/batch', { method: 'POST', body: JSON.stringify({ group_kind: 'batch', items }) })
    await reloadJobs(); setMessage(`${items.length} 个任务已加入队列。`)
  }
  const removePreset = async (id: string) => {
    if (!window.confirm('只删除此预设记录，模型文件会保留。继续吗？')) return
    try { await api(`/api/presets/${encodeURIComponent(id)}`, { method: 'DELETE' }); await reloadPresets() } catch (reason) { reportError(reason) }
  }

  return <div className="app">
    <header className="topbar"><div className="brand"><span className="brand-mark">H</span><strong>Haruka</strong><span className="subtitle">Cover Studio</span></div><span className={`pill ${backendError ? 'error' : backend ? 'ok' : 'pending'}`}>{backendError ? '后端未连接' : backend ? '本地服务就绪' : '正在连接…'}</span></header>
    <nav className="workspace-nav" aria-label="工作空间"><button className={view === 'cover' ? 'active' : ''} onClick={() => setView('cover')}>制作翻唱</button><button className={view === 'queue' ? 'active' : ''} onClick={() => setView('queue')}>批量与队列{activeJobs.length ? `（${activeJobs.length}）` : ''}</button><button className={view === 'models' ? 'active' : ''} onClick={() => setView('models')}>模型管理</button><button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}>历史作品</button><button className="nav-settings" disabled={busy || activeJobs.length > 0} onClick={() => setShowRuntime(true)}>设置与诊断</button></nav>
    <main className="workspace">
      {backendError && <div className="banner error" role="alert">{backendError}</div>}
      {error && <div className="banner error" role="alert">{error}<button className="ghost small" onClick={() => setError('')}>关闭</button></div>}
      {view === 'cover' && <>
        <div className="page-heading"><div><div className="eyebrow">YOUR VOICE, A NEW COLOR</div><h1>给歌声，换一种色彩。</h1><p>导入干声，选择声音，开始你的下一首翻唱。</p></div><span className="local-tag">本地处理</span></div>
        <div className="mode-switch" aria-label="转换范围"><button className={!preview ? 'active' : ''} aria-pressed={!preview} onClick={() => setPreview(false)}>整首制作</button><button className={preview ? 'active' : ''} aria-pressed={preview} onClick={() => setPreview(true)}>片段试唱 / 模型对比</button><span className="muted">先试唱一小段，再决定整首用哪个声音</span></div>
        <div className="input-grid">
          <section className="panel"><div className="section-head"><h2><span className="step">1</span>准备音频</h2><span className="muted">WAV / FLAC / MP3</span></div>
            <button className="drop-zone" disabled={busy} onClick={() => pickFile(setVocalPath, '选择干声')} onDragOver={(event) => event.preventDefault()} onDrop={(event) => dropFile(event, setVocalPath)}>
              <span className="upload-icon">↥</span><strong>{vocalPath ? shortName(vocalPath) : '把干声拖到这里'}</strong><span>{vocalPath ? '点击更换文件' : '或点击选择文件'}</span><small>已分离的人声，不包含伴奏</small>
            </button>
            <div className="backing-row"><label><input type="checkbox" checked={backingEnabled} disabled={busy} onChange={(event) => setBackingEnabled(event.target.checked)} />添加伴奏 <span className="optional">可选</span></label><span className="muted">一起导出混音</span></div>
            {backingEnabled && <div className="backing-fields"><button className="drop-zone backing-drop-zone" title={instrumentalPath || undefined} disabled={busy} onClick={() => pickFile(setInstrumentalPath, '选择伴奏')} onDragOver={(event) => event.preventDefault()} onDrop={(event) => dropFile(event, setInstrumentalPath)}><strong>{instrumentalPath ? shortName(instrumentalPath) : '把伴奏拖到这里'}</strong><span>{instrumentalPath ? '拖入或点击更换伴奏' : '或点击选择伴奏文件'}</span></button><label className="range-label" htmlFor="gain">混音人声增益<span>{gain > 0 ? '+' : ''}{gain} dB</span></label><input id="gain" type="range" min="-12" max="12" step="0.5" value={gain} disabled={busy} onChange={(event) => setGain(Number(event.target.value))} /></div>}
            <p className="input-note">只有干声也可以制作。伴奏需与干声时间轴一致。</p>
            <div className="field song-title"><label htmlFor="song-title">曲名（可选）</label><input id="song-title" value={songTitle} disabled={busy} onChange={(event) => setSongTitle(event.target.value)} placeholder="为这首翻唱起个名字" /></div>
            {preview && <WaveformSelector api={api} path={vocalPath} value={range} onChange={setRange} onReady={setWaveReady} />}
          </section>
          <section className="panel"><div className="section-head"><h2><span className="step">2</span>选择声音</h2><span className="muted">使用模型预设</span></div>
            <div className="voice-heading"><span className="voice-avatar">♫</span><div><h3>{preset?.display_name || '选择你的声音'}</h3><span className="muted">RVC 歌声转换</span></div>{preset?.model_exists === false && <span className="tag warn">模型缺失</span>}</div>
            <div className="field"><label htmlFor="model">模型版本</label><select id="model" value={presetId} disabled={busy} onChange={(event) => setPresetId(event.target.value)}>{!presets.length && <option value="">暂无可用模型</option>}{presets.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></div>
            <p className="model-note">{preset?.description || '在模型管理中导入模型与配套索引。'}</p>
            <div className="field device-field"><label htmlFor="run-device">运行设备</label><select id="run-device" value={device} disabled={busy} onChange={event => setDevice(event.target.value)}>{devices.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select><p className="input-note">{deviceDetail}</p></div>
            <label className="range-label" htmlFor="pitch">升降调<span>{pitch === 0 ? '原调 · 0' : pitch > 0 ? `+${pitch}` : pitch} 半音</span></label><div className="pitch-row"><span>−12</span><input id="pitch" type="range" min="-12" max="12" value={pitch} disabled={busy} onChange={(event) => setPitch(Number(event.target.value))} /><span>+12</span></div>
            <details className="workspace-advanced"><summary>高级参数 <span>按模型配置</span></summary><div className="advanced-grid"><div className="field"><label htmlFor="index">索引比例</label><input id="index" type="number" min="0" max="1" step="0.05" value={indexRate} disabled={busy} onChange={(event) => setIndexRate(Number(event.target.value))} /></div><div className="field"><label htmlFor="protect">辅音保护</label><input id="protect" type="number" min="0" max="0.5" step="0.01" value={protect} disabled={busy} onChange={(event) => setProtect(Number(event.target.value))} /></div><span className="muted">音高提取：{String(preset?.parameters?.f0_method || 'RMVPE').toUpperCase()}</span><span className="muted">{preset?.parameters?.v6b1_global ? '全局条件分块' : '对齐分块'}</span></div></details>
            {preview && <div className="comparison-choices"><strong>想一起比较的模型</strong><div className="model-checks">{presets.filter(item => item.model_exists !== false).map(item => <label key={item.id}><input type="checkbox" checked={compareIds.includes(item.id)} disabled={busy} onChange={event => setCompareIds(current => event.target.checked ? [...current, item.id] : current.filter(id => id !== item.id))} />{item.display_name}</label>)}</div><p className="input-note">比较时使用各模型的预设索引和辅音保护；上方高级参数只作用于单模型任务。</p></div>}
          </section>
        </div>
        <div className="conversion-bar"><div><span className="muted">本次输出{preview ? ` · 选区 ${(range.end - range.start).toFixed(1)} 秒` : ''}</span><p>{backingEnabled ? '纯人声 ＋ 伴奏混音' : '转换后的纯人声'}</p></div><div className="conversion-actions">{preview && <button disabled={busy || !backend || !waveReady || compareIds.length < 2 || compareIds.length > 8} onClick={() => submit(false, true)}>对比所选模型（{compareIds.length}）</button>}<button className="primary" disabled={busy || !backend || !vocalPath || !preset || preset.model_exists === false || (preview && !waveReady)} onClick={() => submit()}>{busy ? '正在提交…' : preview ? '试唱当前模型' : activeJobs.length ? '加入转换队列' : '开始转换'} <span>→</span></button></div></div>
        {comparisonGroup && comparisonJobs.length > 0 && <ComparisonPlayer key={comparisonGroup} api={api} jobs={comparisonJobs} busy={busy} onUse={useComparison} onOpen={openHistory} />}
        <section className="panel results"><div className="section-head"><h2><span className="step">3</span>试听与导出</h2><span className="muted">{job ? STATUSES[job.status] : '等待转换'}</span></div>
          {job && <><div className="progress" role="progressbar" aria-label="转换进度" aria-valuenow={Math.round(job.progress * 100)} aria-valuemin={0} aria-valuemax={100}><div className="progress-bar" style={{ width: `${job.progress * 100}%` }} /></div><div className="progress-meta"><span>{STAGES[job.stage] || job.stage}</span><span>{Math.round(job.progress * 100)}%</span></div>{job.error && <div className="inline-error" role="alert">{job.error}</div>}{running && <button className="ghost small" onClick={async () => { try { setJob(await (await api(`/api/jobs/${job.id}/cancel`, { method: 'POST' })).json()) } catch (reason) { reportError(reason) } }}>取消任务</button>}</>}
          <div className="preview-grid"><div><div className="audio-tabs"><button disabled={!job?.request?.vocal_path || audioBusy} className={track === 'source' ? 'active' : ''} onClick={() => selectTrack('source')}>原声</button><button disabled={!job?.artifacts.some((a) => a.kind === 'vocal_44k') || audioBusy} className={track === 'vocal_44k' ? 'active' : ''} onClick={() => selectTrack('vocal_44k')}>转换后</button>{job?.artifacts.some((a) => a.kind === 'mix') && <button disabled={audioBusy} className={track === 'mix' ? 'active' : ''} onClick={() => selectTrack('mix')}>混音</button>}</div>
            {audioUrl ? <audio className="audio-player" controls autoPlay src={audioUrl} /> : <div className="empty-player"><button aria-label="播放所选轨道" disabled={audioBusy || !job || (track !== 'source' && !output)} onClick={play}>▶</button><span /><small>--:--</small></div>}
          </div><div className="export-controls"><div className="field"><label htmlFor="format">导出格式</label><select id="format" value={format} onChange={(event) => setFormat(event.target.value)}><option value="wav">WAV · 无损</option><option value="flac">FLAC · 无损</option></select></div><button disabled={!output || audioBusy} onClick={exportAudio}>{audioBusy ? '读取音频…' : '导出音频'}</button></div></div>
          <p className="input-note" role="status">{message || (job ? '切换轨道后点击播放，可以对比试听。' : '转换完成后，可以对比试听并保存结果。')}</p>
          {job && <details className="job-details"><summary>任务详情与日志</summary><p className="muted">{job.id} · 升降调 {String(job.request?.pitch_semitones ?? 0)} 半音 · {job.actual_device ? `实际设备 ${job.actual_device}` : `请求设备 ${String(job.request?.device || 'auto')}`} · {job.request?.preview_start != null ? `试唱 ${String(job.request.preview_start)}–${String(job.request.preview_end)} 秒` : '整首'}</p><pre className="log">{(job.log_tail || []).join('\n') || '暂无日志'}</pre><button className="ghost small" onClick={() => window.haruka.openDir(job.output_dir)}>打开输出目录</button></details>}
        </section>
      </>}
      {view === 'queue' && <><div className="page-heading"><div><h1>批量与队列</h1><p>先准备多首歌，再按顺序转换。每首歌的设置独立保存。</p></div></div>{message && <p role="status" className="input-note">{message}</p>}<BatchBuilder presets={presets} device={device} devices={devices} detail={deviceDetail} onDevice={setDevice} onSubmit={submitBatch} /><QueuePanel jobs={history} onOpen={openHistory} onCancel={cancelJob} onRetry={retryJob} /></>}
      {view === 'models' && <><div className="page-heading"><div><h1>模型管理</h1><p>管理声音与配套索引，保留每个模型的默认设置。</p></div><button className="primary compact" onClick={() => setShowImport(true)}>导入模型</button></div><div className="preset-list">{presets.map((item) => <div className="preset-card" key={item.id}><div><strong>{item.display_name}</strong>{item.model_exists === false && <span className="tag warn">模型缺失</span>}<p>{item.description}</p><p className="model-path">{item.model?.path}</p></div><div className="section-actions"><button disabled={busy} onClick={() => { setPresetId(item.id); setView('cover') }}>使用</button>{!item.builtin && <button disabled={busy} className="link-danger" onClick={() => removePreset(item.id)}>删除预设</button>}</div></div>)}</div></>}
      {view === 'history' && <><div className="page-heading"><div><h1>历史作品</h1><p>查看已保存的任务、试听与导出结果。</p></div></div>{!history.length && <p className="muted">还没有作品，从一轨干声开始吧。</p>}<div className="history-list">{history.map((item) => <div className="history-row" key={item.id}><div><strong>{String(item.request?.song_title || item.request?.preset_display_name || '翻唱任务')}</strong><p className="muted">{item.id} · {STATUSES[item.status]}</p></div><button disabled={running && item.id !== job?.id} onClick={() => openHistory(item.id)}>查看作品</button></div>)}</div></>}
      <footer className="workspace-footer"><span>Haruka Cover Studio</span><span>音频与模型保留在你的电脑上</span></footer>
    </main>
    {showImport && <ImportModelDialog api={api} onClose={() => setShowImport(false)} onImported={reloadPresets} />}
    {showDiagnostics && <DiagnosticsDialog api={api} onClose={() => setShowDiagnostics(false)} />}
    {showRuntime && <RuntimeDialog connected={!!backend} onClose={() => setShowRuntime(false)} onDiagnostics={() => { setShowRuntime(false); setShowDiagnostics(true) }} onApplied={info => { setBackend(info); setBackendError(''); setError(''); setJob(null); setAudioUrl(''); setShowRuntime(false) }} />}
  </div>
}
