import { useState } from 'react'
import type { ApiCall } from './types'

type Props = {
  api: ApiCall
  onClose: () => void
  onImported: () => void
}

const F0_METHODS = ['rmvpe', 'rmvpe_gpu', 'harvest', 'crepe', 'pm']
const DEVICES = ['cuda', 'cpu', 'auto']

/** 导入新模型时的默认推理参数，与后端 DEFAULT_PARAMETERS 保持一致 */
function defaultParameters() {
  return {
    f0_method: 'rmvpe',
    index_rate: 0.75,
    rms_mix_rate: 1.0,
    protect: 0.33,
    core_seconds: 7.0,
    context_seconds: 0.5,
    crossfade_ms: 100,
    seed: 20260919,
    rmvpe_device: 'cuda',
    v6b1_global: false,
  }
}

/** 把名称转成合法预设 id；纯中文名称退回时间戳 */
function toPresetId(name: string): string {
  const ascii = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
  return ascii || `import-${Date.now().toString(36)}`
}

export default function ImportModelDialog({ api, onClose, onImported }: Props) {
  const [displayName, setDisplayName] = useState('')
  const [presetId, setPresetId] = useState('')
  const [modelPath, setModelPath] = useState('')
  const [indexPath, setIndexPath] = useState('')
  const [rvcAppRoot, setRvcAppRoot] = useState('')
  const [description, setDescription] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [parameters, setParameters] = useState(defaultParameters())
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const updateParameter = (key: string, value: unknown) =>
    setParameters((current) => ({ ...current, [key]: value }))

  const pickModel = async () => {
    const path = await window.haruka.chooseFile({
      title: '选择 RVC 模型文件',
      filters: [{ name: 'RVC 模型', extensions: ['pth', 'pt'] }],
    })
    if (!path) return
    setModelPath(path)
    // 用文件名自动填充名称和 id，用户可以再改
    const stem = path.split(/[\\/]/).pop()?.replace(/\.(pth|pt)$/i, '') || ''
    if (stem) {
      if (!displayName) setDisplayName(stem)
      if (!presetId) setPresetId(toPresetId(stem))
    }
  }

  const pickIndex = async () => {
    const path = await window.haruka.chooseFile({
      title: '选择检索索引文件（可选）',
      filters: [{ name: 'Faiss 索引', extensions: ['index'] }],
    })
    if (path) setIndexPath(path)
  }

  const submit = async () => {
    setError('')
    if (!displayName.trim()) return setError('请填写预设名称')
    if (!modelPath) return setError('请选择模型文件')
    setBusy(true)
    try {
      await api('/api/presets', {
        method: 'POST',
        body: JSON.stringify({
          id: presetId.trim() || toPresetId(displayName),
          display_name: displayName.trim(),
          description: description.trim() || null,
          model_path: modelPath,
          index_path: indexPath || null,
          rvc_app_root: rvcAppRoot || null,
          parameters,
        }),
      })
      onImported()
      onClose()
    } catch (submitError) {
      setError(String((submitError as Error)?.message || submitError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-mask" onClick={onClose}>
      <div className="modal" onClick={(event) => event.stopPropagation()}>
        <header className="modal-head">
          <h2>导入 RVC 模型</h2>
          <button className="close" onClick={onClose} aria-label="关闭">
            ×
          </button>
        </header>

        <div className="modal-body">
          <p className="muted">
            导入后可在「选择声线」里直接使用。模型与索引文件仍保留在原位置，预设只记录路径和
            SHA-256。
          </p>

          <div className="field">
            <label>预设名称</label>
            <input
              value={displayName}
              onChange={(event) => {
                setDisplayName(event.target.value)
                if (!presetId) setPresetId(toPresetId(event.target.value))
              }}
              placeholder="例如：我的声线"
            />
          </div>

          <div className="field">
            <label>预设 ID（用于文件名，小写字母/数字/连字符）</label>
            <input value={presetId} onChange={(event) => setPresetId(event.target.value)} />
          </div>

          <div className="field">
            <label>模型文件（.pth / .pt，必填）</label>
            <div className="file-row">
              <code title={modelPath}>{modelPath || '尚未选择'}</code>
              <button onClick={pickModel}>选择…</button>
            </div>
          </div>

          <div className="field">
            <label>检索索引（.index，可选，RVC 建议配一个）</label>
            <div className="file-row">
              <code title={indexPath}>{indexPath || '不使用索引'}</code>
              <button onClick={pickIndex}>选择…</button>
              {indexPath && (
                <button className="ghost" onClick={() => setIndexPath('')}>
                  清除
                </button>
              )}
            </div>
          </div>

          <div className="field">
            <label>描述（可选）</label>
            <input value={description} onChange={(event) => setDescription(event.target.value)} />
          </div>

          <div className="field"><label>专用 RVC 代码目录（可选）</label><div className="file-row"><code title={rvcAppRoot}>{rvcAppRoot || '使用环境设置中的目录'}</code><button onClick={async () => { try { const selected = await window.haruka.chooseDirectory('选择此模型配套的 RVC 代码目录'); if (selected) setRvcAppRoot(selected) } catch (reason) { setError(String(reason)) } }}>选择…</button>{rvcAppRoot && <button onClick={() => setRvcAppRoot('')}>清除</button>}</div><p className="input-note">e400、v6e 请使用随模型提供的匹配代码。环境检查通过不代表任意 RVC 模型都兼容。</p></div>

          <button className="ghost small" onClick={() => setShowAdvanced((value) => !value)}>
            {showAdvanced ? '收起高级参数' : '展开高级参数'}
          </button>

          {showAdvanced && (
            <div className="advanced-grid">
              <div className="field">
                <label>f0 方法</label>
                <select
                  value={parameters.f0_method}
                  onChange={(event) => updateParameter('f0_method', event.target.value)}
                >
                  {F0_METHODS.map((method) => (
                    <option key={method} value={method}>
                      {method}
                    </option>
                  ))}
                </select>
              </div>

              <div className="field">
                <label>rmvpe 设备</label>
                <select
                  value={parameters.rmvpe_device}
                  onChange={(event) => updateParameter('rmvpe_device', event.target.value)}
                >
                  {DEVICES.map((device) => (
                    <option key={device} value={device}>
                      {device}
                    </option>
                  ))}
                </select>
              </div>

              {(
                [
                  ['index_rate', '索引混合率', 0, 1, 0.05],
                  ['rms_mix_rate', '响度包络率', 0, 1, 0.05],
                  ['protect', '保护系数', 0, 0.5, 0.01],
                  ['core_seconds', '分块核心长度（秒）', 1, 30, 0.5],
                  ['context_seconds', '上下文长度（秒）', 0, 5, 0.1],
                  ['crossfade_ms', '交叉淡化（毫秒）', 0, 500, 10],
                ] as const
              ).map(([key, label, min, max, step]) => (
                <div className="field" key={key}>
                  <label>{label}</label>
                  <input
                    type="number"
                    min={min}
                    max={max}
                    step={step}
                    value={String(parameters[key as keyof typeof parameters])}
                    onChange={(event) => updateParameter(key, Number(event.target.value))}
                  />
                </div>
              ))}

              <div className="field">
                <label>随机种子</label>
                <input
                  type="number"
                  value={parameters.seed}
                  onChange={(event) => updateParameter('seed', Number(event.target.value))}
                />
              </div>

              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={parameters.v6b1_global}
                  onChange={(event) => updateParameter('v6b1_global', event.target.checked)}
                />
                v6b.1 全局条件管线（仅 v6b.1 模型勾选）
              </label>
            </div>
          )}

          {error && <p className="inline-error">{error}</p>}
        </div>

        <footer className="modal-foot">
          <button className="ghost" onClick={onClose} disabled={busy}>
            取消
          </button>
          <button className="primary" onClick={submit} disabled={busy}>
            {busy ? '导入中…' : '导入'}
          </button>
        </footer>
      </div>
    </div>
  )
}
