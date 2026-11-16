import type { Job } from './types'

const statuses = { queued: '排队中', running: '转换中', succeeded: '已完成', failed: '失败', cancelled: '已取消' }
export default function QueuePanel({ jobs, onOpen, onCancel, onRetry }: { jobs: Job[]; onOpen: (id: string) => void; onCancel: (id: string) => void; onRetry: (id: string) => void }) {
  const active = jobs.filter(job => job.status === 'running' || job.status === 'queued')
  // 先列正在执行与排队的任务，再列最近的结果，避免历史记录掩盖当前进度。
  const ordered = [...active.filter(job => job.status === 'running'), ...active.filter(job => job.status === 'queued').reverse(), ...jobs.filter(job => job.status !== 'running' && job.status !== 'queued')]
  return <section className="panel queue-panel">
    <div className="section-head"><h2>任务队列</h2><span className="muted">{active.length} 项待完成 · 每次运行一项</span></div>
    {!jobs.length && <p className="muted">添加歌曲或试唱任务后，会在这里显示进度。</p>}
    <div className="queue-list">{ordered.map(job => <div className="queue-row" key={job.id}>
      <div className="queue-description"><strong>{String(job.request?.song_title || String(job.request?.vocal_path || '').split(/[\\/]/).pop() || '翻唱任务')}</strong>
        <p>{String(job.request?.preset_display_name || job.request?.preset_id || '')} · {job.request?.preview_start != null ? `片段 ${Number(job.request.preview_start).toFixed(1)}–${Number(job.request.preview_end).toFixed(1)} 秒` : '整首'} · {job.actual_device || String(job.request?.device || 'auto')}</p>
        {job.status === 'running' && <progress aria-label="队列任务进度" max="1" value={job.progress} />}
        {job.error && <p className="inline-error">{job.error}</p>}
      </div>
      <span className={`queue-status ${job.status}`}>{statuses[job.status]}{job.status === 'running' ? ` ${Math.round(job.progress * 100)}%` : ''}</span>
      <div className="queue-actions"><button className="ghost small" onClick={() => onOpen(job.id)}>查看</button>
        {(job.status === 'queued' || job.status === 'running') && <button className="ghost small" onClick={() => onCancel(job.id)}>取消</button>}
        {(job.status === 'failed' || job.status === 'cancelled') && <button className="small" onClick={() => onRetry(job.id)}>重新排队</button>}
      </div>
    </div>)}</div>
    <p className="input-note">取消或失败不会阻塞后续任务。重启后，中断任务可手动重新排队；不会覆盖原有结果。</p>
  </section>
}
