import { useEffect, useState } from 'react'
import type { ApiCall, Diagnostics } from './types'

type Props = {
  api: ApiCall
  onClose: () => void
}

export default function DiagnosticsDialog({ api, onClose }: Props) {
  const [data, setData] = useState<Diagnostics | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    setLoading(true)
    setError('')
    try {
      const response = await api('/api/diagnostics')
      setData(await response.json())
    } catch (loadError) {
      setError(String((loadError as Error)?.message || loadError))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const total = data?.groups.reduce((sum, group) => sum + group.items.length, 0) || 0
  const failed =
    data?.groups.reduce((sum, group) => sum + group.items.filter((item) => !item.ok).length, 0) || 0

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal wide" onClick={(event) => event.stopPropagation()}>
        <header className="modal-head">
          <h2>环境诊断</h2>
          <button className="close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="modal-body">
          {loading && <p className="muted">正在检查运行时、GPU、模型与磁盘…</p>}
          {error && <p className="inline-error">{error}</p>}

          {data && (
            <>
              <p className="muted">
                检查时间 {data.checked_at} · {total} 项中 {failed} 项异常
              </p>
              {data.groups.map((group) => (
                <section className="diag-group" key={group.id}>
                  <h3>{group.title}</h3>
                  {group.items.map((item) => (
                    <div className="diag-row" key={`${group.id}-${item.name}`}>
                      <span className={`dot ${item.ok ? 'ok' : 'bad'}`} />
                      <div>
                        <strong>{item.name}</strong>
                        <p>{item.detail}</p>
                      </div>
                    </div>
                  ))}
                </section>
              ))}
            </>
          )}
        </div>

        <footer className="modal-foot">
          <button className="ghost" onClick={onClose}>
            关闭
          </button>
          <button className="primary" onClick={load} disabled={loading}>
            {loading ? '检查中…' : '重新检查'}
          </button>
        </footer>
      </div>
    </div>
  )
}
