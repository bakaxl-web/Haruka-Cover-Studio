<#
.SYNOPSIS
  构建整合包使用的自包含 Python 运行时、RVC 应用副本与共享音频工具。

.DESCRIPTION
  RVC 推理环境固定要求 FastAPI<0.100 / pydantic 1.x / gradio 3.14，
  与本产品后端（FastAPI 0.115 / pydantic 2.x）不兼容，因此必须分成多个环境：

    runtime/python-base     基础解释器（3.12），两个 venv 共用，保证安装路径可迁移
    runtime/python-backend  后端 API 环境（fastapi 等）
    runtime/python-rvc      RVC 推理环境（torch 2.7.1+cu118 等）
    runtime/rvc-app         RVC 应用源码副本（不含 .venv、模型、日志）
    runtime/ffmpeg          ffmpeg 可执行文件（解码 m4a/aac 等格式）

  产物由 electron-builder 作为 extraResources 打入整合包。
  注意：本脚本会重建 runtime 目录下的环境，执行前确认没有其他构建在使用它们。
#>
param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path,
  [Parameter(Mandatory=$true)][string]$BasePythonSource,
  [Parameter(Mandatory=$true)][string]$RvcAppRoot,
  [string]$FfmpegSource = ''
)

$ErrorActionPreference = 'Stop'

$runtimeDir = Join-Path $ProjectRoot 'runtime'
$pythonBase = Join-Path $runtimeDir 'python-base'
$backendEnv = Join-Path $runtimeDir 'python-backend'
$rvcEnv = Join-Path $runtimeDir 'python-rvc'
$rvcAppDir = Join-Path $runtimeDir 'rvc-app'
$ffmpegDir = Join-Path $runtimeDir 'ffmpeg'
$pipCache = Join-Path $ProjectRoot '.cache\pip'

if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot 'backend\requirements.txt'))) {
  throw "未找到 backend\requirements.txt，ProjectRoot 可能不正确：$ProjectRoot"
}
if (-not (Test-Path -LiteralPath $RvcAppRoot)) {
  throw "RVC 应用目录不存在：$RvcAppRoot"
}


New-Item -ItemType Directory -Force -Path $runtimeDir, $pipCache | Out-Null
$env:PIP_CACHE_DIR = $pipCache

# 0) 基础解释器：所有 venv 共用同一份，打包后由 main.js 重写 pyvenv.cfg 的 home 实现可迁移
if (Test-Path -LiteralPath $pythonBase) {
  Write-Host "复用已有基础解释器：$pythonBase"
} else {
  if (-not (Test-Path -LiteralPath $BasePythonSource)) {
    throw "基础 Python 不存在：$BasePythonSource"
  }
  Write-Host "复制基础解释器：$BasePythonSource → $pythonBase"
  & robocopy $BasePythonSource $pythonBase /E /XD __pycache__ /XF *.pyc /NFL /NDL /NJH /NJS /NP | Out-Null
  if ($LASTEXITCODE -ge 8) { throw "复制基础解释器失败（robocopy 退出码 $LASTEXITCODE）" }
}
$basePython = Join-Path $pythonBase 'python.exe'

function New-CleanVenv([string]$Path) {
  if (Test-Path -LiteralPath $Path) {
    Write-Host "移除旧环境：$Path"
    Remove-Item -LiteralPath $Path -Recurse -Force
  }
  Write-Host "创建环境：$Path"
  & $basePython -m venv $Path | Out-Null
  if ($LASTEXITCODE -ne 0) { throw "创建 venv 失败：$Path" }
  $python = Join-Path $Path 'Scripts\python.exe'
  & $python -m pip install --upgrade pip --quiet
  if ($LASTEXITCODE -ne 0) { throw "pip 升级失败：$Path" }
  # 只把解释器路径作为返回值，避免函数吞掉外部命令输出导致调用方拿到数组
  return $python
}

$pkuIndex = 'https://mirrors.pku.edu.cn/pypi/simple'
$torchIndex = 'https://mirrors.nju.edu.cn/pytorch/whl/cu118'

# 1) 后端 API 环境
$backendPython = New-CleanVenv $backendEnv
Write-Host '安装后端依赖…'
& $backendPython -m pip install -r (Join-Path $ProjectRoot 'backend\requirements.txt') --index-url $pkuIndex
if ($LASTEXITCODE -ne 0) { throw '安装后端依赖失败' }

# 2) RVC 推理环境（分两步：先装 cu118 torch 组合，再装其余依赖）
$rvcPython = New-CleanVenv $rvcEnv
Write-Host '安装 torch 2.7.1+cu118…'
& $rvcPython -m pip install torch==2.7.1+cu118 torchaudio==2.7.1+cu118 --index-url $torchIndex --extra-index-url $pkuIndex
if ($LASTEXITCODE -ne 0) { throw '安装 torch cu118 失败' }

Write-Host '安装 RVC 依赖…'
& $rvcPython -m pip install -r (Join-Path $RvcAppRoot 'requirments_cu118_py312.txt') --index-url $pkuIndex
if ($LASTEXITCODE -ne 0) { throw '安装 RVC 依赖失败' }

# 4) 复制 RVC 应用源码（不包含模型、虚拟环境与日志）
if (Test-Path -LiteralPath $rvcAppDir) {
  Write-Host "移除旧 RVC 副本：$rvcAppDir"
  Remove-Item -LiteralPath $rvcAppDir -Recurse -Force
}
Write-Host "复制 RVC 应用源码：$RvcAppRoot → $rvcAppDir"
$excludeDirs = @('.venv', '.venv_cloud_cu126', '.git', 'logs', 'assets', '.model-downloads', '__pycache__')
$excludeFiles = @('*.pyc')
& robocopy $RvcAppRoot $rvcAppDir /E /XD @excludeDirs /XF @excludeFiles /NFL /NDL /NJH /NJS /NP | Out-Null
if ($LASTEXITCODE -ge 8) { throw "复制 RVC 应用失败（robocopy 退出码 $LASTEXITCODE）" }

# 7) ffmpeg（用于解码 m4a/aac 等 libsndfile 不支持的格式）
if ($FfmpegSource -and (Test-Path -LiteralPath $FfmpegSource)) {
  New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null
  Copy-Item -LiteralPath $FfmpegSource -Destination (Join-Path $ffmpegDir 'ffmpeg.exe') -Force
  Write-Host "复制 ffmpeg：$FfmpegSource"
} else {
  $found = Get-Command ffmpeg -ErrorAction SilentlyContinue
  if ($found) {
    New-Item -ItemType Directory -Force -Path $ffmpegDir | Out-Null
    Copy-Item -LiteralPath $found.Source -Destination (Join-Path $ffmpegDir 'ffmpeg.exe') -Force
    Write-Host "复制 ffmpeg：$($found.Source)"
  } else {
    Write-Host '警告：未找到 ffmpeg，整合包将无法解码 m4a/aac'
  }
}

# 8) 记录基础解释器相对位置，供 main.js 在目标机器上重写 pyvenv.cfg
foreach ($envDir in @($backendEnv, $rvcEnv)) {
  $cfg = Join-Path $envDir 'pyvenv.cfg'
  if (-not (Test-Path -LiteralPath $cfg)) { continue }
  Copy-Item -LiteralPath $cfg -Destination "$cfg.bak" -Force
  $content = Get-Content -LiteralPath $cfg
  $content = $content -replace '^home = .*$', "home = $pythonBase"
  Set-Content -LiteralPath $cfg -Value $content -Encoding utf8NoBOM
}

Write-Host '运行时构建完成：'
Get-ChildItem $runtimeDir | Select-Object Name, @{n = 'GB'; e = { [math]::Round((Get-ChildItem $_.FullName -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum / 1GB, 2) } } | Format-Table -AutoSize
