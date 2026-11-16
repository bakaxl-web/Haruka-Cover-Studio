"""音频合同校验：任务预检与产物验收共用同一套规则。

所有检查失败都抛出 ContractError，消息面向用户，直接展示在界面上。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import soundfile as sf


class ContractError(RuntimeError):
    """音频或模型文件不满足约定。"""


def sha256_file(path: Path, block_size: int = 1 << 20) -> str:
    """流式计算文件 SHA-256。"""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(block_size), b""):
            digest.update(block)
    return digest.hexdigest()


def probe_audio(path: Path) -> dict:
    """读取音频元信息，不整段加载到内存。"""
    target = Path(path)
    if not target.is_file():
        raise ContractError(f"音频文件不存在：{target}")
    try:
        with sf.SoundFile(str(target)) as handle:
            frames = len(handle)
            return {
                "path": str(target),
                "samplerate": int(handle.samplerate),
                "channels": int(handle.channels),
                "frames": int(frames),
                "duration": float(frames) / float(handle.samplerate) if handle.samplerate else 0.0,
                "format": handle.format,
                "subtype": handle.subtype,
            }
    except (OSError, RuntimeError) as error:
        raise ContractError(f"无法解码音频：{target}（{error}）") from error


def check_finite(path: Path, block_frames: int = 1 << 20) -> None:
    """分块检查非有限值，避免整首歌一次性进内存。"""
    target = Path(path)
    with sf.SoundFile(str(target)) as handle:
        while True:
            block = handle.read(block_frames, dtype="float32", always_2d=True)
            if block.size == 0:
                break
            if not np.isfinite(block).all():
                raise ContractError(f"音频包含 NaN/Inf：{target}")


def validate_inputs(vocal_path: Path, instrumental_path: Path | None = None) -> dict:
    """校验干声与伴奏的配对合同，返回带 SHA-256 的输入摘要。

    干声允许单声道或双声道：推理脚本 read_source 会对双声道取均值降混，
    因此这里只要求可解码且声道数合理，不要求用户预先转换。
    """
    vocal = probe_audio(vocal_path)
    if vocal["channels"] not in (1, 2):
        raise ContractError(f"干声必须是单声道或双声道，实际为 {vocal['channels']} 声道：{vocal['path']}")
    if vocal["frames"] == 0:
        raise ContractError("干声不能为空")
    check_finite(vocal_path)
    vocal["sha256"] = sha256_file(vocal_path)
    # 不提供伴奏时，纯人声转换无需满足双轨配对条件。
    if instrumental_path is None:
        return {"vocal": vocal, "instrumental": None}
    instrumental = probe_audio(instrumental_path)
    check_finite(instrumental_path)
    if instrumental["channels"] != 2:
        raise ContractError(f"伴奏必须是双声道，实际为 {instrumental['channels']} 声道：{instrumental['path']}")
    if vocal["samplerate"] != instrumental["samplerate"]:
        raise ContractError(
            f"采样率不一致：干声 {vocal['samplerate']} Hz，伴奏 {instrumental['samplerate']} Hz"
        )
    if abs(vocal["frames"] - instrumental["frames"]) > 1:
        raise ContractError(
            f"帧数不一致：干声 {vocal['frames']}，伴奏 {instrumental['frames']}"
            f"（相差 {abs(vocal['frames'] - instrumental['frames'])} 帧）"
        )

    instrumental["sha256"] = sha256_file(instrumental_path)
    return {"vocal": vocal, "instrumental": instrumental}


def validate_output(path: Path, expect_samplerate: int | None = None, expect_channels: int | None = None) -> dict:
    """校验产物的采样率、声道、帧数与有限值，返回产物摘要。"""
    info = probe_audio(path)
    if expect_samplerate is not None and info["samplerate"] != expect_samplerate:
        raise ContractError(f"产物采样率不符：期望 {expect_samplerate}，实际 {info['samplerate']}")
    if expect_channels is not None and info["channels"] != expect_channels:
        raise ContractError(f"产物声道数不符：期望 {expect_channels}，实际 {info['channels']}")
    check_finite(path)
    info["sha256"] = sha256_file(path)
    return info
