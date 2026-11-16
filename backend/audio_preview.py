"""只在任务目录创建选区和试听副本，不改写原音频。"""
from __future__ import annotations

import hashlib
import math
import os
import threading
from pathlib import Path

import numpy as np
import soundfile as sf

from .contracts import ContractError, probe_audio

_cache_lock = threading.Lock()


def validate_selection(start, end, duration):
    if start is None and end is None:
        return
    if start is None or end is None or not all(math.isfinite(x) for x in (start, end)):
        raise ContractError("试唱起止时间必须同时提供且为有限数值")
    if not 0 <= start < end <= duration:
        raise ContractError("试唱区间须满足 0 ≤ 开始 < 结束 ≤ 音频时长")
    if not 1 <= end - start <= 60:
        raise ContractError("试唱长度必须在 1 至 60 秒之间")


def waveform(path: Path) -> dict:
    info = probe_audio(path)
    if info['frames'] <= 0:
        raise ContractError('音频不能为空')
    bins = min(1200, info['frames'])
    peaks = np.zeros(bins, dtype=np.float64)
    offset = 0
    with sf.SoundFile(path) as handle:
        while True:
            block = handle.read(65536, dtype='float32', always_2d=True)
            if not len(block):
                break
            if not np.isfinite(block).all():
                raise ContractError('音频包含 NaN/Inf')
            indices = (np.arange(offset, offset + len(block), dtype=np.int64) * bins) // info['frames']
            np.maximum.at(peaks, indices, np.max(np.abs(block), axis=1))
            offset += len(block)
    maximum = float(peaks.max())
    if maximum > 0:
        peaks /= maximum
    return {key: info[key] for key in ('duration', 'samplerate', 'frames')} | {'peaks': peaks.tolist()}


def extract(path: Path, target: Path, start: float, end: float) -> dict:
    """只读取实际选择的采样点，边界使用四舍五入并记录到报告。"""
    with sf.SoundFile(path) as handle:
        first = round(start * handle.samplerate)
        last = min(len(handle), round(end * handle.samplerate))
        handle.seek(first)
        data = handle.read(last - first, dtype='float32', always_2d=True)
        if not len(data) or not np.isfinite(data).all():
            raise ContractError('选区为空或包含 NaN/Inf')
        sf.write(target, data, handle.samplerate, subtype='FLOAT')
        return {'start_frame': first, 'end_frame': last, 'samplerate': handle.samplerate,
                'start': first / handle.samplerate, 'end': last / handle.samplerate}


def source_preview(job: dict) -> Path:
    request = job['request']
    source = Path(request['vocal_path'])
    if request.get('preview_start') is None:
        return source
    target = Path(job['output_dir']) / '.source_preview.wav'
    with _cache_lock:
        if not target.is_file():
            extract(source, target, request['preview_start'], request['preview_end'])
    return target


def normalized_copy(path: Path, job_dir: Path) -> Path:
    """RMS 音量匹配到约 -20 dBFS；极低电平保持原样，峰值限制 0.98。"""
    stat = path.stat()
    key = hashlib.sha256(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()[:20]
    target = job_dir / f'.listen_{key}.wav'
    with _cache_lock:
        if target.is_file():
            return target
        square_sum, count, peak = 0., 0, 0.
        with sf.SoundFile(path) as handle:
            for block in handle.blocks(blocksize=65536, dtype='float32', always_2d=True):
                if not np.isfinite(block).all():
                    raise ContractError('音频包含 NaN/Inf')
                square_sum += float(np.square(block.astype(np.float64)).sum())
                count += block.size
                peak = max(peak, float(np.max(np.abs(block))))
        if not count:
            raise ContractError('音频不能为空')
        rms = math.sqrt(square_sum / count)
        gain = min(.1 / rms, .98 / peak) if rms > 1e-4 and peak > 0 else 1.
        temporary = target.with_suffix('.tmp.wav')
        with sf.SoundFile(path) as source, sf.SoundFile(temporary, 'w', samplerate=source.samplerate,
                                                     channels=source.channels, subtype='PCM_16') as output:
            for block in source.blocks(blocksize=65536, dtype='float32', always_2d=True):
                output.write(block * gain)
        os.replace(temporary, target)
    return target
