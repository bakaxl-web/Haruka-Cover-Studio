import { useEffect, useRef, useState } from 'react'
import type { ApiCall, Job } from './types'

export default function ComparisonPlayer({ api, jobs, busy, onUse, onOpen }: { api: ApiCall; jobs: Job[]; busy: boolean; onUse: (job: Job) => void; onOpen: (id: string) => void }) {
  const [selected, setSelected] = useState('')
  const [normalized, setNormalized] = useState(true)
  const [url, setUrl] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const audio = useRef<HTMLAudioElement>(null)
  const position = useRef(0)
  const resume = useRef(false)
  const completed = jobs.filter(job => job.status === 'succeeded' && job.artifacts.some(item => item.kind === 'vocal_44k'))
  const first = completed[0]
  useEffect(() => { if (!selected && first) setSelected(`${first.id}:vocal_44k`) }, [selected, first?.id])
  const [jobId, kind] = selected.split(':')
  const current = jobs.find(job => job.id === jobId)
  const artifact = current?.artifacts.find(item => item.kind === kind)
  useEffect(() => {
    if (!current || (kind !== 'source' && !artifact)) return
    const controller = new AbortController()
    let objectUrl = ''
    setLoading(true); setError('')
    const route = kind === 'source' ? `/api/jobs/${jobId}/source` : `/api/jobs/${jobId}/artifacts/${encodeURIComponent(artifact!.name)}`
    api(`${route}?normalize=${normalized}`, { signal: controller.signal }).then(response => response.blob()).then(blob => {
      if (controller.signal.aborted) return
      objectUrl = URL.createObjectURL(blob); setUrl(objectUrl); setLoading(false)
    }).catch(reason => { if (!controller.signal.aborted) { setError(String(reason.message || reason)); setLoading(false) } })
    return () => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) }
  }, [api, jobId, kind, artifact?.name, normalized])
  const remember = () => {
    // 所有比较音频共用时间轴；换模型仅替换音源，保留当前试听位置。
    position.current = audio.current?.currentTime || 0
    resume.current = audio.current ? !audio.current.paused : true
    audio.current?.pause()
  }
  const choose = (key: string) => { if (key !== selected) { remember(); setSelected(key) } }
  return <section className="panel comparison-panel">
    <div className="section-head"><h2>模型对比试听</h2><span className="muted">{completed.length} / {jobs.length} 已完成</span></div>
    <p className="input-note">同一选区、升降调和设备，按队列依次生成。各模型保留自己的索引和辅音保护预设。</p>
    <div className="comparison-models">
      <button disabled={!first || loading} className={kind === 'source' ? 'active' : ''} onClick={() => first && choose(`${first.id}:source`)}>原声片段</button>
      {jobs.map(job => <button key={job.id} disabled={job.status !== 'succeeded' || loading} className={job.id === jobId && kind !== 'source' ? 'active' : ''} onClick={() => choose(`${job.id}:vocal_44k`)}>
        <strong>{String(job.request?.preset_display_name || '模型')}</strong><small>{job.status === 'succeeded' ? '点击试听' : job.status === 'running' ? `${Math.round(job.progress * 100)}%` : job.status === 'queued' ? '排队中' : job.status === 'cancelled' ? '已取消' : '失败，可在队列重试'}</small>
      </button>)}
    </div>
    <label className="inline-check"><input type="checkbox" checked={normalized} disabled={loading} onChange={event => { remember(); setNormalized(event.target.checked) }} />匹配试听音量<span className="muted">按 RMS 调整并限制峰值，仅影响试听</span></label>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {loading && <p className="muted" role="status">正在准备试听…</p>}
    {url && <audio ref={audio} className="audio-player" controls src={url} onLoadedMetadata={() => {
      if (!audio.current) return
      audio.current.currentTime = Math.min(position.current, Math.max(0, audio.current.duration - 0.05))
      if (resume.current) void audio.current.play().catch(() => { /* 浏览器限制自动播放时由用户点播放。 */ })
    }} />}
    {current && kind !== 'source' && <div className="comparison-actions"><button disabled={busy} onClick={() => onUse(current)}>采用此模型制作整首</button><button className="ghost" onClick={() => onOpen(current.id)}>查看原始产物 / 导出</button><span className="muted">{current.actual_device ? `实际设备：${current.actual_device}` : ''}</span></div>}
  </section>
}
