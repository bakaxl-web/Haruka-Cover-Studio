"""FastAPI 入口：本地任务 API，只绑定 127.0.0.1 并由一次性 token 保护。"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
import io
import os
import shutil
import subprocess
import sys
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from . import config
from . import audio_preview
from . import jobs as job_module
from .contracts import ContractError, probe_audio
from .engines import rvc, smoke

BACKEND_TOKEN = os.environ.get("HARUKA_BACKEND_TOKEN", "")
VERSION = "0.2.3"

app = FastAPI(title="Haruka Cover Studio", version=VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ENGINES = {"rvc": rvc.run, "smoke": smoke.run}


def require_token(x_haruka_token: Optional[str] = Header(default=None)) -> None:
    """校验后端令牌；未配置令牌时（测试环境）放行。"""
    if not BACKEND_TOKEN:
        return
    if x_haruka_token != BACKEND_TOKEN:
        raise HTTPException(status_code=401, detail="无效的后端令牌")


def gpu_summary() -> dict:
    """通过 nvidia-smi 汇总 GPU 信息，失败时返回不可用。"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            devices = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            return {"available": True, "devices": devices}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"available": False, "devices": []}


class CreateJobRequest(BaseModel):
    """创建干声转换任务，伴奏可选；参数仅覆盖本次任务。"""

    kind: Optional[str] = Field(default=None, description="cover（默认）")
    # RVC 翻唱参数
    vocal_path: Optional[str] = None
    instrumental_path: Optional[str] = None
    preset_id: Optional[str] = None
    pitch_semitones: int = Field(default=0, ge=-12, le=12, strict=True)
    index_rate: Optional[float] = Field(default=None, ge=0, le=1)
    protect: Optional[float] = Field(default=None, ge=0, le=0.5)
    vocal_gain_db: Optional[float] = Field(default=None, ge=-12, le=12)
    device: str = Field(default="auto", pattern=r"^(auto|cpu|cuda:[0-9]+)$")
    preview_start: Optional[float] = Field(default=None, allow_inf_nan=False)
    preview_end: Optional[float] = Field(default=None, allow_inf_nan=False)
    # 通用
    song_title: Optional[str] = None
    engine: Optional[str] = Field(default=None, description="仅开发自检使用 smoke")


def _job_payload(job: dict, log_lines: int = 40) -> dict:
    """把内部任务对象裁剪成前端需要的字段。"""
    return {
        "id": job["id"],
        "status": job["status"],
        "stage": job["stage"],
        "progress": job["progress"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error": job["error"],
        "actual_device": job.get("actual_device"),
        "artifacts": job.get("artifacts", []),
        "output_dir": job["output_dir"],
        "request": {key: value for key, value in job.get("request", {}).items() if not key.startswith("_")},
        "log_tail": job_module.store.log_tail(job["id"], log_lines),
    }


@app.get("/api/health", dependencies=[Depends(require_token)])
def health() -> dict:
    presets = config.load_presets()
    environment = config.summarize_environment()
    return {
        "status": "ok",
        "version": VERSION,
        "gpu": gpu_summary(),
        "presets": len(presets),
        "environment": environment,
    }


@app.get("/api/presets", dependencies=[Depends(require_token)])
def list_presets() -> list[dict]:
    return config.load_presets()


@app.get("/api/jobs", dependencies=[Depends(require_token)])
def list_jobs() -> list[dict]:
    return [_job_payload(job, log_lines=0) for job in job_module.store.list_all()]


def _submit(request: dict, runner) -> dict:
    """创建任务并启动执行线程，返回前端需要的任务载荷。"""
    job = job_module.store.create(request)
    job_module.store.start(job["id"], runner)
    return {"job_id": job["id"], "job": _job_payload(job_module.store.get(job["id"]))}


def _prepare_cover_job(payload: CreateJobRequest) -> tuple[dict, object]:
    """RVC 翻唱任务：需要干声与声线，提供伴奏时才混音。"""
    if not payload.vocal_path:
        raise HTTPException(status_code=400, detail="翻唱任务需要 vocal_path")
    if (payload.kind or "cover").strip().lower() != "cover":
        raise HTTPException(status_code=400, detail="只支持 cover 任务")
    preset_map = config.presets_by_id()
    preset = preset_map.get(payload.preset_id or "")
    engine_name = payload.engine or (preset or {}).get("engine")
    if payload.engine == "smoke":
        engine_name = "smoke"
        preset = preset or {"id": "smoke", "display_name": "自检", "engine": "smoke"}
    if preset is None:
        raise HTTPException(status_code=404, detail=f"未知预设：{payload.preset_id}")
    runner = ENGINES.get(engine_name or "")
    if runner is None:
        raise HTTPException(status_code=400, detail=f"不支持的引擎：{engine_name}")

    # 轻量预检：只读元信息，完整有限值校验在引擎执行时进行
    if engine_name != "smoke" or payload.preview_start is not None or payload.preview_end is not None:
        try:
            vocal_info = probe_audio(Path(payload.vocal_path))
            if vocal_info['frames'] <= 0:
                raise ContractError('干声不能为空')
            if vocal_info['channels'] not in (1, 2):
                raise ContractError('干声必须为单声道或双声道')
            audio_preview.validate_selection(payload.preview_start, payload.preview_end, vocal_info['duration'])
            if payload.instrumental_path:
                backing = probe_audio(Path(payload.instrumental_path))
                if backing['channels'] != 2 or backing['samplerate'] != vocal_info['samplerate'] or abs(backing['frames'] - vocal_info['frames']) > 1:
                    raise ContractError('伴奏须为双声道，且与干声采样率、帧数一致')
        except ContractError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    # 独立复制预设，避免本次滑杆设置污染模型默认值。
    preset = deepcopy(preset)
    for key in ("index_rate", "protect"):
        value = getattr(payload, key)
        if value is not None:
            preset.setdefault("parameters", {})[key] = value
    if engine_name == 'rvc':
        # 只检查本次实际使用的文件，不读取模型权重或完整音频；整批通过后才排队。
        model_path = Path(preset.get('model', {}).get('path') or '')
        if not model_path.is_file() or model_path.stat().st_size == 0:
            raise HTTPException(400, f'模型文件不存在或为空：{model_path}')
        if preset.get('parameters', {}).get('index_rate', 0) > 0:
            index_path = Path(preset.get('index', {}).get('path') or '')
            if not index_path.is_file() or index_path.stat().st_size == 0:
                raise HTTPException(400, f'启用检索时需要有效索引文件：{index_path}')
    request = {
        "kind": "cover",
        "vocal_path": str(Path(payload.vocal_path).resolve()),
        "instrumental_path": str(Path(payload.instrumental_path).resolve()) if payload.instrumental_path else None,
        "pitch_semitones": payload.pitch_semitones,
        "device": payload.device,
        "preview_start": payload.preview_start,
        "preview_end": payload.preview_end,
        "vocal_gain_db": payload.vocal_gain_db,
        "preset_id": payload.preset_id,
        "preset_display_name": preset.get("display_name", payload.preset_id),
        "song_title": payload.song_title,
        "engine": engine_name,
        "_preset": preset,
    }
    return request, runner


@app.post("/api/jobs", dependencies=[Depends(require_token)])
def create_job(payload: CreateJobRequest) -> dict:
    """只接收干声转换；旧任务类型显式拒绝。"""
    kind = (payload.kind or "cover").strip().lower()
    if kind != "cover":
        raise HTTPException(status_code=400, detail=f"不支持的任务类型：{kind}")
    return _submit(*_prepare_cover_job(payload))


class BatchJobRequest(BaseModel):
    items: list[CreateJobRequest] = Field(min_length=1, max_length=100)
    group_kind: Literal['comparison', 'batch']


@app.post('/api/jobs/batch', dependencies=[Depends(require_token)])
def create_batch(payload: BatchJobRequest) -> dict:
    # 所有轻量校验先完成，坏项不会留下已排队的半批任务。
    prepared = [_prepare_cover_job(item) for item in payload.items]
    if payload.group_kind == 'comparison':
        if not 2 <= len(prepared) <= 8 or len({r['preset_id'] for r, _ in prepared}) != len(prepared):
            raise HTTPException(400, '模型比较需要 2 至 8 个不同预设')
        keys = ('vocal_path', 'instrumental_path', 'preview_start', 'preview_end', 'pitch_semitones', 'device')
        if any(any(request[key] != prepared[0][0][key] for key in keys) for request, _ in prepared[1:]):
            raise HTTPException(400, '模型比较必须使用相同音源、伴奏、区间、升降调和设备')
    group_id = secrets.token_hex(8)
    result = []
    for request, runner in prepared:
        request.update(group_id=group_id, group_kind=payload.group_kind)
        result.append(_submit(request, runner)['job'])
    return {'group_id': group_id, 'jobs': result}


@app.post('/api/jobs/{job_id}/retry', dependencies=[Depends(require_token)])
def retry_job(job_id: str) -> dict:
    try:
        job = job_module.store.get(job_id)
    except job_module.JobNotFoundError as error:
        raise HTTPException(404, '任务不存在') from error
    if job['status'] not in ('failed', 'cancelled'):
        raise HTTPException(409, '仅失败或已取消任务可以重试')
    request = deepcopy(job['request'])
    runner = ENGINES.get(request.get('engine'))
    if runner is None:
        raise HTTPException(400, '原任务引擎不可用')
    return _submit(request, runner)


class WaveformRequest(BaseModel):
    path: str


@app.post('/api/audio/waveform', dependencies=[Depends(require_token)])
def get_waveform(payload: WaveformRequest) -> dict:
    try:
        return audio_preview.waveform(Path(payload.path))
    except (ContractError, OSError, RuntimeError) as error:
        raise HTTPException(400, str(error)) from error


@app.get("/api/jobs/{job_id}", dependencies=[Depends(require_token)])
def get_job(job_id: str) -> dict:
    try:
        job = job_module.store.get(job_id)
    except job_module.JobNotFoundError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    return _job_payload(job)


@app.post("/api/jobs/{job_id}/cancel", dependencies=[Depends(require_token)])
def cancel_job(job_id: str) -> dict:
    try:
        job_module.store.cancel(job_id)
        return _job_payload(job_module.store.get(job_id))
    except job_module.JobNotFoundError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error


@app.get("/api/jobs/{job_id}/events", dependencies=[Depends(require_token)])
async def job_events(job_id: str) -> StreamingResponse:
    """SSE 进度流：任务进入终态后自动结束。"""

    async def generator():
        last_payload = None
        while True:
            try:
                job = job_module.store.get(job_id)
            except job_module.JobNotFoundError:
                yield 'data: {"error":"not_found"}\n\n'
                return
            payload = _job_payload(job, log_lines=40)
            text = json.dumps(payload, ensure_ascii=False)
            if text != last_payload:
                yield f"data: {text}\n\n"
                last_payload = text
            if job["status"] in job_module.TERMINAL_STATUSES:
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(generator(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}/source", dependencies=[Depends(require_token)])
def play_source(job_id: str, normalize: bool = False) -> FileResponse:
    """只播放已提交任务记录的干声，不接受任意文件路径。"""
    try:
        job = job_module.store.get(job_id)
    except job_module.JobNotFoundError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    source = job.get("request", {}).get("vocal_path")
    if not source or not Path(source).is_file():
        raise HTTPException(status_code=404, detail="原始干声不存在")
    try:
        source = audio_preview.source_preview(job)
        if normalize:
            source = audio_preview.normalized_copy(source, Path(job['output_dir']))
    except (ContractError, OSError, RuntimeError) as error:
        raise HTTPException(400, str(error)) from error
    return FileResponse(source)


@app.get("/api/jobs/{job_id}/artifacts/{name}", dependencies=[Depends(require_token)])
def download_artifact(job_id: str, name: str, format: Optional[Literal["wav", "flac"]] = None, normalize: bool = False):
    try:
        job = job_module.store.get(job_id)
    except job_module.JobNotFoundError as error:
        raise HTTPException(status_code=404, detail="任务不存在") from error
    if Path(name).name != name:
        raise HTTPException(status_code=400, detail="非法文件名")
    target = Path(job["output_dir"]) / name
    if not target.is_file():
        raise HTTPException(status_code=404, detail="产物不存在")
    if normalize:
        if target.suffix.lower() not in ('.wav', '.flac'):
            raise HTTPException(400, '只有音频可以进行试听音量匹配')
        try:
            return FileResponse(audio_preview.normalized_copy(target, Path(job['output_dir'])), media_type='audio/wav')
        except (ContractError, OSError, RuntimeError) as error:
            raise HTTPException(400, str(error)) from error
    if format == "flac":
        import soundfile as sf
        if target.suffix.lower() != ".wav":
            raise HTTPException(status_code=400, detail="只有音频产物可以导出 FLAC")
        # 浮点试唱与旧 PCM16 均按归一化振幅导出；原始文件保持不变。
        samples, rate = sf.read(target, dtype="float32")
        buffer = io.BytesIO()
        sf.write(buffer, samples, rate, format="FLAC", subtype="PCM_16")
        buffer.seek(0)
        return StreamingResponse(buffer, media_type="audio/flac")
    return FileResponse(target)


class CreatePresetRequest(BaseModel):
    id: str
    display_name: str
    description: Optional[str] = None
    model_path: str
    index_path: Optional[str] = None
    rvc_app_root: Optional[str] = None
    parameters: dict = Field(default_factory=dict)


@app.post("/api/presets", dependencies=[Depends(require_token)])
def create_preset(payload: CreatePresetRequest) -> dict:
    """导入一个 RVC 模型：校验文件与参数后写入用户预设目录。"""
    try:
        return config.create_preset(payload.model_dump())
    except config.PresetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


@app.delete("/api/presets/{preset_id}", dependencies=[Depends(require_token)])
def delete_preset(preset_id: str) -> dict:
    """删除用户导入的预设；内置预设不可删除。"""
    try:
        config.delete_preset(preset_id)
    except config.PresetError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return {"deleted": preset_id}


def _probe_python(executable: Path, code: str, timeout: float = 45.0) -> dict:
    """在指定解释器里执行一段检查代码，返回解析后的 JSON 结果或错误信息。"""
    if not executable.is_file():
        return {"ok": False, "error": f"解释器不存在：{executable}"}
    try:
        result = subprocess.run(
            [str(executable), "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        return {"ok": False, "error": str(error)}
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-900:]
        return {"ok": False, "error": detail or f"退出码 {result.returncode}"}
    try:
        return {"ok": True, "data": json.loads(result.stdout.strip().splitlines()[-1])}
    except (ValueError, IndexError):
        return {"ok": True, "data": {"raw": result.stdout.strip()[-900:]}}


RVC_PROBE = (
    "import json,sys;"
    "import torch;"
    "print(json.dumps({'python': sys.version.split()[0], 'torch': torch.__version__,"
    "'cuda': torch.cuda.is_available(),"
    "'device': torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}))"
)


@app.get('/api/devices', dependencies=[Depends(require_token)])
def list_devices() -> dict:
    devices = [{'id': 'auto', 'label': '自动选择', 'kind': 'auto'}, {'id': 'cpu', 'label': 'CPU（兼容模式）', 'kind': 'cpu'}]
    detail = '自动选择可用 NVIDIA CUDA，否则使用 CPU。AMD / DirectML 尚未支持，请使用 CPU。'
    code = ("import torch,json;print(json.dumps({'devices':[{'id':'cuda:'+str(i),'label':torch.cuda.get_device_name(i),'kind':'cuda'} for i in range(torch.cuda.device_count())] if torch.cuda.is_available() else []}))")
    try:
        probe = _probe_python(Path(config.resolve_inference_python()), code)
        if probe['ok']:
            devices.extend(probe['data'].get('devices', []))
        else:
            detail += ' 检测失败：' + probe['error']
    except (OSError, RuntimeError) as error:
        detail += ' 检测失败：' + str(error)
    return {'devices': devices, 'detail': detail}

@app.get("/api/diagnostics", dependencies=[Depends(require_token)])
def diagnostics() -> dict:
    """环境自检：运行时、GPU、模型、存储四组检查，供界面「环境诊断」页展示。"""
    environment = config.summarize_environment()
    runtime_items: list[dict] = [
        {
            "name": "后端 Python",
            "ok": True,
            "detail": f"{sys.executable}（Python {environment['python']}）",
        }
    ]

    rvc_python = None
    try:
        rvc_python = config.resolve_inference_python()
    except FileNotFoundError as error:
        runtime_items.append({"name": "RVC 推理解释器", "ok": False, "detail": str(error)})
    if rvc_python:
        probe = _probe_python(Path(rvc_python), RVC_PROBE)
        if probe["ok"]:
            data = probe["data"]
            runtime_items.append(
                {
                    "name": "RVC 推理解释器",
                    "ok": True,
                    "detail": f"{rvc_python}（Python {data.get('python')} · torch {data.get('torch')} · CUDA {data.get('cuda')}）",
                }
            )
        else:
            runtime_items.append({"name": "RVC 推理解释器", "ok": False, "detail": probe["error"]})

    runtime_items.append(
        {
            "name": "RVC 应用代码",
            "ok": environment["rvc_app_exists"],
            "detail": environment["rvc_app_root"],
        }
    )
    ffmpeg_ok = False
    ffmpeg_path = config.ffmpeg_executable()
    ffmpeg_detail = "未找到 ffmpeg（影响 m4a/aac 等压缩格式解码）"
    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"], capture_output=True, text=True, timeout=8, check=False
        )
        if result.returncode == 0:
            ffmpeg_ok = True
            ffmpeg_detail = result.stdout.splitlines()[0] if result.stdout else "ffmpeg 可用"
    except (OSError, subprocess.SubprocessError):
        pass
    runtime_items.append({"name": "ffmpeg", "ok": ffmpeg_ok, "detail": ffmpeg_detail})

    gpu = gpu_summary()
    gpu_items = [
        {
            "name": "NVIDIA GPU",
            "ok": gpu["available"],
            "detail": " / ".join(gpu["devices"]) if gpu["devices"] else "未检测到 NVIDIA GPU（nvidia-smi 不可用）",
        }
    ]

    preset_items: list[dict] = []
    for preset in config.load_presets():
        problems = []
        if not preset["model_exists"]:
            problems.append("模型文件缺失")
        if not preset["index_exists"]:
            problems.append("索引文件缺失")
        preset_items.append(
            {
                "name": preset.get("display_name") or preset["id"],
                "ok": not problems,
                "detail": (
                    f"{preset['id']} · {preset.get('engine')}"
                    + (f" · {'、'.join(problems)}" if problems else " · 文件完整")
                ),
            }
        )
    if not preset_items:
        preset_items.append({"name": "声线预设", "ok": False, "detail": "尚未导入任何模型"})

    storage_items: list[dict] = []
    try:
        usage = shutil.disk_usage(str(config.OUTPUT_ROOT if config.OUTPUT_ROOT.exists() else config.PROJECT_ROOT))
        free_gb = usage.free / (1024**3)
        storage_items.append(
            {
                "name": "输出磁盘剩余空间",
                "ok": free_gb > 5,
                "detail": f"{free_gb:.1f} GB 可用（{config.OUTPUT_ROOT}）",
            }
        )
    except OSError as error:
        storage_items.append({"name": "输出磁盘剩余空间", "ok": False, "detail": str(error)})

    writable = True
    writable_detail = str(config.OUTPUT_ROOT)
    try:
        config.OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
        probe_file = config.OUTPUT_ROOT / ".write-probe"
        probe_file.write_text("ok", encoding="utf-8")
        probe_file.unlink(missing_ok=True)
    except OSError as error:
        writable = False
        writable_detail = f"{config.OUTPUT_ROOT}：{error}"
    storage_items.append({"name": "输出目录可写", "ok": writable, "detail": writable_detail})

    return {
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "groups": [
            {"id": "runtime", "title": "运行时", "items": runtime_items},
            {"id": "gpu", "title": "GPU", "items": gpu_items},
            {"id": "models", "title": "模型与预设", "items": preset_items},
            {"id": "storage", "title": "存储", "items": storage_items},
        ],
    }
