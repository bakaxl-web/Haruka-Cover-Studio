<#
.SYNOPSIS
  构建 Windows 免安装整合包。

.DESCRIPTION
  前置条件：
    - 已运行 packaging/build-runtime.ps1，runtime/ 下各运行时与源码副本就绪；
    - 已安装 node_modules。

  产物：release/HarukaCoverStudio-<version>-win-x64.zip
#>
param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
)

$ErrorActionPreference = 'Stop'
$configPath = Join-Path $ProjectRoot 'packaging\electron-builder.yml'

# runtime/ 是打包唯一必需的外部资产，逐项检查避免打出半成品包
$required = [ordered]@{
  '基础解释器'   = 'runtime\python-base\python.exe'
  '后端运行时'   = 'runtime\python-backend\Scripts\python.exe'
  'RVC 推理运行时' = 'runtime\python-rvc\Scripts\python.exe'
  'RVC 应用副本' = 'runtime\rvc-app\infer\cli.py'
  'ffmpeg'       = 'runtime\ffmpeg\ffmpeg.exe'
}

if (-not (Test-Path -LiteralPath $configPath)) { throw "缺少 electron-builder 配置：$configPath" }

$missing = @()
foreach ($name in $required.Keys) {
  $path = Join-Path $ProjectRoot $required[$name]
  if (-not (Test-Path -LiteralPath $path)) { $missing += "$name（$path）" }
}
if ($missing.Count -gt 0) {
  throw ("缺少运行时资产：`n  " + ($missing -join "`n  ") + "`n请先运行 packaging\build-runtime.ps1")
}

Push-Location $ProjectRoot
try {
  # electron-builder 的下载缓存也放在 D 盘，避免占满 C 盘
  $env:ELECTRON_BUILDER_CACHE = Join-Path $ProjectRoot '.cache\electron-builder'

  # 1) 构建渲染进程
  Write-Host '构建渲染进程…'
  & npm run build:web
  if ($LASTEXITCODE -ne 0) { throw '前端构建失败' }

  # 2) 打包（target 由 electron-builder.yml 决定：zip 解压即用）
  Write-Host '执行 electron-builder…'
  & npx electron-builder --win zip --config $configPath
  if ($LASTEXITCODE -ne 0) { throw 'electron-builder 打包失败' }

  $releaseDir = Join-Path $ProjectRoot 'release'
  Write-Host '构建产物：'
  Get-ChildItem $releaseDir -File -ErrorAction SilentlyContinue |
    Select-Object Name, @{n = 'GB'; e = { [math]::Round($_.Length / 1GB, 2) } } |
    Format-Table -AutoSize
}
finally {
  Pop-Location
}
