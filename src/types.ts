// 前后端共享的数据结构类型定义
export type RuntimeSettings = { backendPython: string; inferencePython: string; rvcAppRoot: string; ffmpeg: string }
export type RuntimeReport = { ok: boolean; items: DiagnosticItem[]; backend?: BackendInfo | null }
export type RuntimeDiscovery = { settings: RuntimeSettings; pythons: { path: string; torch: boolean; backend: boolean }[]; rvcApps: { path: string; complete: boolean }[]; ffmpegs: string[]; scannedDirectories: number; limited: boolean }
export type BackendInfo = {
  baseUrl: string
  token: string
  outputRoot: string
  health: unknown
}

export type Preset = {
  id: string
  display_name: string
  engine: string
  description?: string
  /** 内置预设来自程序目录，用户导入的来自 %APPDATA% */
  builtin?: boolean
  /** 打包分发后内置预设指向作者本机路径，模型可能不存在 */
  model_exists?: boolean
  index_exists?: boolean
  model?: { path: string; sha256?: string }
  index?: { path: string; sha256?: string }
  parameters?: Record<string, unknown>
  output?: { instrumental_boost_db?: number }
}

export type Artifact = {
  name: string
  path: string
  kind: string
  size: number
  sha256?: string
}

export type Job = {
  id: string
  status: 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled'
  stage: string
  progress: number
  error?: string | null
  artifacts: Artifact[]
  output_dir: string
  log_tail?: string[]
  request?: Record<string, unknown>
}

export type ApiCall = (path: string, init?: RequestInit) => Promise<Response>

export type DiagnosticItem = {
  name: string
  ok: boolean
  detail: string
}

export type DiagnosticGroup = {
  id: string
  title: string
  items: DiagnosticItem[]
}

export type Diagnostics = {
  checked_at: string
  groups: DiagnosticGroup[]
}
