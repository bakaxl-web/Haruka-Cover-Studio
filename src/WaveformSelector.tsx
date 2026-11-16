import { useEffect, useRef, useState } from 'react'
import type { ApiCall, PreviewRange } from './types'

type Waveform = { duration: number; peaks: number[] }
const stamp = (value: number) => `${Math.floor(value / 60)}:${(value % 60).toFixed(1).padStart(4, '0')}`

export default function WaveformSelector({ api, path, value, onChange, onReady }: {
  api: ApiCall; path: string; value: PreviewRange; onChange: (range: PreviewRange) => void; onReady: (ready: boolean) => void
}) {
  const [wave, setWave] = useState<Waveform | null>(null)
  const [error, setError] = useState('')
  const drag = useRef<number | null>(null)
  const callbacks = useRef({ onChange, onReady })
  callbacks.current = { onChange, onReady }
  useEffect(() => {
    const controller = new AbortController()
    setWave(null); setError(''); callbacks.current.onReady(false)
    if (!path) return () => controller.abort()
    api('/api/audio/waveform', { method: 'POST', body: JSON.stringify({ path }), signal: controller.signal })
      .then(response => response.json()).then((data: Waveform) => {
        if (controller.signal.aborted) return
        if (data.duration < 1) { setError('片段试唱需要至少 1 秒音频。'); return }
        setWave(data); callbacks.current.onChange({ start: 0, end: Math.min(20, data.duration) }); callbacks.current.onReady(true)
      }).catch(reason => { if (!controller.signal.aborted) setError(String(reason.message || reason)) })
    return () => { controller.abort(); callbacks.current.onReady(false) }
  }, [api, path])
  const at = (event: React.PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect()
    return Math.max(0, Math.min(wave!.duration, (event.clientX - rect.left) / rect.width * wave!.duration))
  }
  const select = (start: number, end: number) => {
    if (!wave) return
    // 统一限制选区长度，避免拖拽和数值输入产生不同的时间范围。
    start = Math.max(0, Math.min(start, wave.duration - 1))
    end = Math.max(start + 1, Math.min(end, start + 60, wave.duration))
    const roundedStart = Math.min(wave.duration - 1, Math.round(start * 1000) / 1000)
    onChange({ start: roundedStart, end: Math.min(wave.duration, Math.max(roundedStart + 1, Math.round(end * 1000) / 1000)) })
  }
  return <div className="waveform-selector">
    <div className="section-head"><strong>选择试唱片段</strong><span className="muted">拖拽波形，或输入起止秒数</span></div>
    {error && <p className="inline-error" role="alert">{error}</p>}
    {!wave && !error && <p className="muted">{path ? '正在读取波形…' : '先添加一首干声'}</p>}
    {wave && <>
      <svg className="waveform" viewBox="0 0 1000 100" preserveAspectRatio="none" aria-label="音频波形选区"
        onPointerDown={event => { if (event.button !== 0) return; drag.current = at(event); event.currentTarget.setPointerCapture(event.pointerId) }}
        onPointerMove={event => { if (drag.current !== null) { const pos = at(event); select(Math.min(drag.current, pos), Math.max(drag.current, pos)) } }}
        onPointerUp={event => { if (drag.current !== null) { const pos = at(event); if (Math.abs(drag.current - pos) < 0.1) select(pos, pos + Math.min(20, wave.duration)); drag.current = null; event.currentTarget.releasePointerCapture(event.pointerId) } }}
        onPointerCancel={() => { drag.current = null }}>
        <rect width="1000" height="100" fill="#f4f6f0" />
        {wave.peaks.map((peak, i) => <line key={i} x1={i / wave.peaks.length * 1000} x2={i / wave.peaks.length * 1000} y1={50 - peak * 43} y2={50 + peak * 43} stroke="#9dac95" strokeWidth="1.5" />)}
        <rect x={value.start / wave.duration * 1000} width={(value.end - value.start) / wave.duration * 1000} height="100" fill="#bd6153" opacity=".18" />
        {[value.start, value.end].map((point, i) => <line key={i} x1={point / wave.duration * 1000} x2={point / wave.duration * 1000} y1="0" y2="100" stroke="#b35b4f" strokeWidth="3" />)}
      </svg>
      <div className="waveform-scale"><span>0:00</span><span>{stamp(wave.duration)}</span></div>
      <div className="range-fields"><label>起点（秒）<input aria-label="试唱起点" type="number" min="0" max={Math.max(0, wave.duration - 1)} step="0.1" value={value.start} onChange={event => select(Number(event.target.value), value.end)} /></label><label>终点（秒）<input aria-label="试唱终点" type="number" min={value.start + 1} max={Math.min(value.start + 60, wave.duration)} step="0.1" value={value.end} onChange={event => select(value.start, Number(event.target.value))} /></label><span className="range-duration">{(value.end - value.start).toFixed(1)} 秒</span></div>
      <p className="input-note">试唱范围 1～60 秒。转换时读取前后上下文，试听和导出仅保留选区。</p>
    </>}
  </div>
}
