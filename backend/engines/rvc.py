"""RVC 引擎：子进程调用 vendor 脚本完成推理，再做 44.1k 重采样、混音与产物校验。

设计要点：
- 推理代码不复制算法，直接复用 Voice-Forge 的已验证脚本；
- 子进程输出逐行转发到任务日志，并按 chunk 行更新进度；
- 用户取消时结束整个进程树。
"""
from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import threading
import json
from pathlib import Path

from .. import config
from .. import audio_preview
from ..contracts import ContractError, sha256_file, validate_inputs, validate_output
from ..jobs import JobContext

CHUNK_PATTERN = re.compile(r"^chunk (\d+)/(\d+):")
CHUNK_PROGRESS_BASE = 0.30
CHUNK_PROGRESS_SPAN = 0.55

RVC_SCRIPT = config.VENDOR_DIR / "run_rvc_aligned.py"
MIX_SCRIPT = config.VENDOR_DIR / "mix_vocal_plus_gain.py"


class JobCancelled(RuntimeError):
    """用户取消任务。"""


def _artifact(path: Path, kind: str) -> dict:
    """生成产物条目，附带大小与哈希。"""
    return {
        "name": path.name,
        "path": str(path),
        "kind": kind,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _terminate(process: subprocess.Popen) -> None:
    """结束推理进程树，Windows 下必须用 taskkill /T。"""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/pid", str(process.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        process.terminate()


def _build_inference_command(preset: dict, request: dict, output_path: Path) -> list[str]:
    """把预设与任务输入翻译成 run_rvc_aligned.py 的命令行。"""
    params = preset["parameters"]
    command = [
        str(config.resolve_inference_python()),
        str(RVC_SCRIPT),
        "--source", request["vocal_path"],
        "--model", preset["model"]["path"],
        "--output", str(output_path),
        "--f0-method", str(params["f0_method"]),
        "--index-rate", str(params["index_rate"]),
        "--rms-mix-rate", str(params["rms_mix_rate"]),
        "--protect", str(params["protect"]),
        "--core-seconds", str(params["core_seconds"]),
        "--context-seconds", str(params["context_seconds"]),
        "--crossfade-ms", str(params["crossfade_ms"]),
        "--seed", str(params["seed"]),
        "--rmvpe-device", str(params.get("rmvpe_device", "auto")),
        "--pitch-semitones", str(request.get("pitch_semitones", 0)),
    ]
    index_path = preset.get("index", {}).get("path")
    if request.get('device') is not None:
        command += ['--device', request['device']]
    if index_path:
        command += ["--index", index_path]
    if params.get("v6b1_global"):
        command.append("--v6b1-global")
    if params.get("strict_output_frames", True):
        command.append("--strict-output-frames")
    return command


def _run_inference(preset: dict, request: dict, output_path: Path, job_dir: Path, ctx: JobContext) -> None:
    """执行推理子进程，转发日志并更新进度。"""
    if not RVC_SCRIPT.is_file():
        raise ContractError(f"缺少推理脚本：{RVC_SCRIPT}（应位于 backend/vendor/）")

    command = _build_inference_command(preset, request, output_path)
    ctx.log("[rvc] 推理命令：" + " ".join(command))
    ctx.stage("loading_runtime", CHUNK_PROGRESS_BASE * 0.2)

    environment = dict(os.environ)
    # 不同声线可能依赖不同版本的 RVC 应用（例如 v6b.1 需要专用 app 才能识别模型标记）
    rvc_app_root = preset.get("rvc_app_root") or str(config.RVC_APP_ROOT)
    environment.update(
        {
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUTF8": "1",
            "HARUKA_RVC_APP_ROOT": str(rvc_app_root),
            "NUMBA_CACHE_DIR": str(config.PROJECT_ROOT / ".cache" / "numba"),
        }
    )

    process = subprocess.Popen(
        command,
        cwd=str(config.PROJECT_ROOT),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )

    # 独立观察取消标志，子进程长期不输出日志时也可以立即结束。
    finished = threading.Event()
    def watch_cancel():
        while not finished.wait(.1):
            if ctx.cancel_requested:
                _terminate(process)
                return
    watcher = threading.Thread(target=watch_cancel, daemon=True)
    watcher.start()
    total_chunks = 0
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip()
            if not line:
                continue
            ctx.log(line)
            if ctx.cancel_requested:
                _terminate(process)
                raise JobCancelled("任务已取消")
            chunk_match = CHUNK_PATTERN.match(line)
            if chunk_match:
                done = int(chunk_match.group(1))
                total = int(chunk_match.group(2))
                if total > 0:
                    total_chunks = total
                    ratio = min(1.0, done / total)
                    ctx.stage("converting", CHUNK_PROGRESS_BASE + CHUNK_PROGRESS_SPAN * ratio)
        returncode = process.wait()
    finally:
        finished.set()
        if process.poll() is None:
            _terminate(process)
        process.wait()
        watcher.join(timeout=2)
        if process.stdout is not None:
            process.stdout.close()

    if ctx.cancel_requested:
        raise JobCancelled('任务已取消')
    if returncode != 0:
        raise RuntimeError(f"RVC 推理失败（退出码 {returncode}），详见任务日志")
    if not output_path.is_file():
        raise RuntimeError(f"推理结束但未找到输出文件：{output_path}")
    ctx.log(f"[rvc] 推理完成，共 {total_chunks} 个块")


def _resample_to_44k(vocal_40k: Path, output_44k: Path, ctx: JobContext, expected_frames: int | None = None) -> dict:
    """把 40 kHz 纯人声重采样到 44.1 kHz，帧数按比例取整截断。"""
    import numpy as np
    import soundfile as sf

    ctx.stage("resampling", CHUNK_PROGRESS_BASE + CHUNK_PROGRESS_SPAN + 0.02)
    audio, samplerate = sf.read(str(vocal_40k), dtype="float32", always_2d=False)
    if samplerate != 40000:
        raise ContractError(f"预期 40 kHz 推理产物，实际 {samplerate} Hz")

    if expected_frames is None:
        expected_frames = int(len(audio) * 44100 / 40000)
    runtime_path = config.VENDOR_DIR / "rvc_runtime.py"
    converted = None
    if runtime_path.is_file():
        spec = importlib.util.spec_from_file_location("haruka_vendor_rvc_runtime", runtime_path)
        if spec is not None and spec.loader is not None:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            converted = module.resample_audio(np.asarray(audio), samplerate, 44100)
    if converted is None:
        from scipy.signal import resample_poly

        converted = resample_poly(np.asarray(audio, dtype=np.float32), 441, 400)

    converted = np.asarray(converted, dtype=np.float32)
    if len(converted) > expected_frames:
        converted = converted[:expected_frames]
    elif len(converted) < expected_frames:
        converted = np.pad(converted, (0, expected_frames - len(converted)), mode="edge")
    if not np.isfinite(converted).all():
        raise ContractError("44.1 kHz 重采样输出包含非有限值")

    sf.write(str(output_44k), converted, 44100, subtype="PCM_16")
    info = validate_output(output_44k, expect_samplerate=44100, expect_channels=1)
    report = {
        "status": "technical_pass",
        "input_40k": str(vocal_40k),
        "output_44k": str(output_44k),
        "samplerate": 44100,
        "frames": int(len(converted)),
        "expected_source_frames": expected_frames,
        "channels": 1,
        "finite": True,
        "peak": float(np.max(np.abs(converted))),
        "rms": float(np.sqrt(np.mean(np.square(converted)))),
        "sha256": info["sha256"],
    }
    output_44k.with_name(output_44k.stem + ".report.json").write_text(
        json_dumps(report), encoding="utf-8"
    )
    return report


def json_dumps(payload: dict) -> str:
    """统一的中文 JSON 序列化格式。"""
    import json

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _mix(vocal_44k: Path, instrumental: Path, output: Path, boost_db: float, ctx: JobContext) -> None:
    """调用 vendor 混音脚本，保持与历史产物一致的算法与报告字段。"""
    if not MIX_SCRIPT.is_file():
        raise ContractError(f"缺少混音脚本：{MIX_SCRIPT}")
    ctx.stage("mixing", 0.93)
    command = [
        sys.executable,
        str(MIX_SCRIPT),
        "--vocal", str(vocal_44k),
        "--instrumental", str(instrumental),
        "--output", str(output),
        "--boost-db", str(boost_db),
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, encoding='utf-8', errors='replace')
    try:
        while True:
            if ctx.cancel_requested:
                _terminate(process)
                raise JobCancelled('任务已取消')
            try:
                stdout, stderr = process.communicate(timeout=.1)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            _terminate(process)
        process.communicate()
    ctx.log(stdout.strip())
    if process.returncode != 0:
        ctx.log(stderr.strip())
        raise RuntimeError(f"混音失败（退出码 {process.returncode}）")
    validate_output(output, expect_samplerate=44100, expect_channels=2)


def run(job: dict, ctx: JobContext) -> list[dict]:
    """执行一次完整 RVC 翻唱任务，返回产物清单。"""
    request = job["request"]
    preset = request["_preset"]
    job_dir = Path(job["output_dir"])
    preset_id = preset["id"]

    ctx.stage("probe", 0.02)
    ctx.log(f"[rvc] 预设：{preset['display_name']}（{preset_id}）")
    ctx.log(f"[rvc] 干声：{request['vocal_path']}")
    ctx.log(f"[rvc] 伴奏：{request['instrumental_path']}")

    # 推理前先做输入合同校验，避免白跑一次 GPU
    instrumental = Path(request["instrumental_path"]) if request.get("instrumental_path") else None
    inputs = validate_inputs(Path(request["vocal_path"]), instrumental)

    vocal_40k = job_dir / f"converted_vocal_40k_mono_{preset_id}.wav"
    vocal_44k = job_dir / f"converted_vocal_44k_mono_{preset_id}_exact.wav"
    song_title = request.get("song_title") or "cover"
    mix_output = job_dir / f"{song_title}_{preset_id}_伴奏混音.wav"

    preview = request.get('preview_start') is not None
    selection = None
    if preview:
        start, end = request['preview_start'], request['preview_end']
        audio_preview.validate_selection(start, end, inputs['vocal']['duration'])
        context_path = job_dir / '.inference_context.wav'
        context = audio_preview.extract(Path(request['vocal_path']), context_path,
                                        max(0., start - .5), min(inputs['vocal']['duration'], end + .5))
        source_path = audio_preview.source_preview(job)
        selection = {'original_vocal_path': request['vocal_path'], 'original_instrumental_path': request.get('instrumental_path'),
                     'start': start, 'end': end, 'context': context, 'source_preview': str(source_path)}
        inference_output = job_dir / '.converted_context.wav'
        _run_inference(preset, dict(request, vocal_path=str(context_path)), inference_output, job_dir, ctx)
        import soundfile as sf
        import numpy as np
        samples, rate = sf.read(inference_output, dtype='float32')
        first = round((start - context['start']) * 40000)
        count = round((end - start) * 40000)
        if rate != 40000 or first + count > len(samples):
            raise ContractError('试唱推理输出未完整覆盖所选区间')
        sf.write(vocal_40k, samples[first:first + count], rate, subtype='FLOAT')
        validate_output(vocal_40k, expect_samplerate=40000, expect_channels=1)
        report = json.loads(inference_output.with_suffix('.report.json').read_text(encoding='utf-8'))
        report['preview'] = selection
        report['context_output'] = report.get('output')
        report['output'] = validate_output(vocal_40k, expect_samplerate=40000, expect_channels=1)
        vocal_40k.with_suffix('.report.json').write_text(json_dumps(report), encoding='utf-8')
        if instrumental is not None:
            backing_path = job_dir / '.instrumental_selection.wav'
            audio_preview.extract(instrumental, backing_path, start, end)
            backing_audio, backing_rate = sf.read(backing_path, dtype='float32', always_2d=True)
            from scipy.signal import resample_poly
            from math import gcd
            divisor = gcd(backing_rate, 44100)
            backing_audio = resample_poly(backing_audio, 44100 // divisor, backing_rate // divisor, axis=0)
            count_44k = round((end - start) * 44100)
            backing_audio = backing_audio[:count_44k]
            if len(backing_audio) < count_44k:
                backing_audio = np.pad(backing_audio, ((0, count_44k - len(backing_audio)), (0, 0)), mode='edge')
            instrumental = job_dir / '.instrumental_44k.wav'
            sf.write(instrumental, backing_audio, 44100, subtype='FLOAT')
    else:
        _run_inference(preset, request, vocal_40k, job_dir, ctx)
    inference_report = json.loads(vocal_40k.with_suffix('.report.json').read_text(encoding='utf-8'))
    if inference_report.get('actual_device'):
        ctx.update(actual_device=inference_report['actual_device'])
    if ctx.cancel_requested:
        raise JobCancelled("任务已取消")

    _resample_to_44k(vocal_40k, vocal_44k, ctx, round((request['preview_end'] - request['preview_start']) * 44100) if preview else None)
    if ctx.cancel_requested:
        raise JobCancelled("任务已取消")

    if instrumental is not None:
        # 历史字段虽然名为 instrumental_boost_db，实际算法提升的是人声。
        boost_db = request.get("vocal_gain_db")
        if boost_db is None:
            boost_db = preset.get("output", {}).get("instrumental_boost_db", 3.0)
        _mix(vocal_44k, instrumental, mix_output, float(boost_db), ctx)

    ctx.stage("validating", 0.98)
    artifacts = [
        _artifact(vocal_40k, "vocal_40k"),
        _artifact(vocal_44k, "vocal_44k"),
        _artifact(job_dir / f"converted_vocal_40k_mono_{preset_id}.report.json", "report"),
        _artifact(vocal_44k.with_name(vocal_44k.stem + ".report.json"), "report"),
    ]
    if instrumental is not None:
        artifacts.extend([
            _artifact(mix_output, "mix"),
            _artifact(mix_output.with_name(mix_output.stem + ".report.json"), "report"),
        ])
    ctx.log(f"[rvc] 产物：{len(artifacts)} 个文件")
    return artifacts
