"""后端配置：解释器、目录、模型库与运行参数的统一解析入口。

所有路径都通过本模块解析，业务代码不得硬编码本机路径。
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .contracts import sha256_file

PROJECT_ROOT = Path(os.environ.get("HARUKA_PROJECT_ROOT", Path(__file__).resolve().parent.parent)).resolve()
BACKEND_DIR = Path(__file__).resolve().parent
PRESET_DIR = BACKEND_DIR / "presets"
VENDOR_DIR = BACKEND_DIR / "vendor"

OUTPUT_ROOT = Path(os.environ.get("HARUKA_OUTPUT_ROOT", PROJECT_ROOT / "outputs")).resolve()

# 默认使用项目内运行时；外部环境由启动器显式注入，避免绑定开发机目录。
DEFAULT_RVC_APP_ROOT = PROJECT_ROOT / "runtime" / "rvc-app"
RVC_APP_ROOT = Path(os.environ.get("HARUKA_RVC_APP_ROOT", DEFAULT_RVC_APP_ROOT)).resolve()

# 推理用的 Python 解释器：需要 torch。优先环境变量，其次后端自身解释器。
DEFAULT_INFERENCE_PYTHON = RVC_APP_ROOT / ".venv" / "Scripts" / "python.exe"

# 音频解码共享工具，由打包环境注入。
FFMPEG = Path(os.environ.get("HARUKA_FFMPEG", "ffmpeg")).resolve() if os.environ.get("HARUKA_FFMPEG") else None

PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
SUPPORTED_F0_METHODS = {"rmvpe", "rmvpe_gpu", "harvest", "crepe", "pm"}
SUPPORTED_RMVPE_DEVICES = {"auto", "cpu", "cuda", "cuda:0", "cuda:1"}

# 导入新模型时的默认推理参数（用户可在表单里覆盖）
DEFAULT_PARAMETERS = {
    "f0_method": "rmvpe",
    "index_rate": 0.75,
    "rms_mix_rate": 1.0,
    "protect": 0.33,
    "core_seconds": 7.0,
    "context_seconds": 0.5,
    "crossfade_ms": 100.0,
    "seed": 20260919,
    "rmvpe_device": "cuda",
    "v6b1_global": False,
}


class PresetError(ValueError):
    """预设校验或写入失败。"""


def _user_preset_dir() -> Path:
    """用户导入预设的存放目录：优先环境变量，其次 %APPDATA%\\haruka-cover-studio\\presets。"""
    configured = os.environ.get("HARUKA_USER_PRESET_DIR")
    if configured:
        return Path(configured).resolve()
    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else (Path.home() / ".config")
    return (base / "haruka-cover-studio" / "presets").resolve()


USER_PRESET_DIR = _user_preset_dir()


def resolve_inference_python() -> Path:
    """返回执行 RVC 推理的 Python 解释器路径。"""
    configured = os.environ.get("HARUKA_INFERENCE_PYTHON")
    candidates = [Path(configured)] if configured else []
    candidates.append(DEFAULT_INFERENCE_PYTHON)
    candidates.append(Path(sys.executable))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise FileNotFoundError(f"找不到推理解释器，已尝试：{[str(c) for c in candidates]}")


def _load_json_dir(directory: Path, builtin: bool) -> list[dict]:
    """读取目录下全部 JSON 预设，忽略损坏文件。"""
    presets: list[dict] = []
    if not directory.is_dir():
        return presets
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict) or not data.get("id"):
            continue
        # 随包预设使用资源目录相对路径，解压位置改变后重新解析，不改写预设文件。
        if builtin:
            for field in ("model", "index"):
                value = (data.get(field) or {}).get("path")
                if value and not Path(value).is_absolute():
                    data[field]["path"] = str((PROJECT_ROOT / value).resolve())
            value = data.get("rvc_app_root")
            if value and not Path(value).is_absolute():
                data["rvc_app_root"] = str((PROJECT_ROOT / value).resolve())
        data["_source"] = str(path)
        data["builtin"] = builtin
        presets.append(data)
    return presets


def load_presets() -> list[dict]:
    """读取内置与用户预设（用户 id 覆盖内置），并标记模型文件是否存在。

    打包分发给别人时内置预设指向作者本机路径，模型必然缺失，
    因此前端需要 model_exists 标记来提示「模型缺失」而不是直接报错。
    """
    merged: dict[str, dict] = {}
    for preset in _load_json_dir(PRESET_DIR, builtin=True) + _load_json_dir(USER_PRESET_DIR, builtin=False):
        merged[preset["id"]] = preset

    result: list[dict] = []
    for preset in sorted(merged.values(), key=lambda item: (not item["builtin"], item["id"])):
        model_path = (preset.get("model") or {}).get("path") or ""
        index_path = (preset.get("index") or {}).get("path") or ""
        preset["model_exists"] = bool(model_path) and Path(model_path).is_file()
        preset["index_exists"] = Path(index_path).is_file() if index_path else True
        result.append(preset)
    return result


def presets_by_id() -> dict[str, dict]:
    """返回 id 到预设的映射。"""
    return {preset["id"]: preset for preset in load_presets()}


def _require_number(parameters: dict, key: str, low: float, high: float | None = None) -> float:
    """读取并校验数值参数，超出范围时抛 PresetError。"""
    raw = parameters.get(key, DEFAULT_PARAMETERS[key])
    try:
        value = float(raw)
    except (TypeError, ValueError) as error:
        raise PresetError(f"参数 {key} 必须是数字，实际为 {raw!r}") from error
    if value < low or (high is not None and value > high):
        upper = "" if high is None else f" ~ {high}"
        raise PresetError(f"参数 {key} 超出范围 {low}{upper}：{value}")
    return value


def normalize_parameters(raw: dict | None) -> dict:
    """合并默认参数并逐项校验，返回规范化后的参数字典。"""
    merged = dict(DEFAULT_PARAMETERS)
    if raw:
        merged.update({key: value for key, value in raw.items() if key in DEFAULT_PARAMETERS})

    f0_method = str(merged["f0_method"])
    if f0_method not in SUPPORTED_F0_METHODS:
        raise PresetError(f"不支持的 f0_method：{f0_method}，可选 {sorted(SUPPORTED_F0_METHODS)}")
    rmvpe_device = str(merged["rmvpe_device"])
    if rmvpe_device not in SUPPORTED_RMVPE_DEVICES:
        raise PresetError(f"不支持的 rmvpe_device：{rmvpe_device}，可选 {sorted(SUPPORTED_RMVPE_DEVICES)}")

    result = {
        "f0_method": f0_method,
        "index_rate": _require_number(merged, "index_rate", 0.0, 1.0),
        "rms_mix_rate": _require_number(merged, "rms_mix_rate", 0.0, 1.0),
        "protect": _require_number(merged, "protect", 0.0, 0.5),
        "core_seconds": _require_number(merged, "core_seconds", 1.0, 60.0),
        "context_seconds": _require_number(merged, "context_seconds", 0.0, 10.0),
        "crossfade_ms": _require_number(merged, "crossfade_ms", 0.0, 1000.0),
        "seed": int(merged["seed"]),
        "rmvpe_device": rmvpe_device,
        "v6b1_global": bool(merged["v6b1_global"]),
    }
    if result["crossfade_ms"] > result["core_seconds"] * 1000:
        raise PresetError("crossfade_ms 不能大于 core_seconds")
    return result


def create_preset(payload: dict) -> dict:
    """校验并写入一个用户预设，返回规范化后的预设字典。

    payload 字段：id、display_name、description、model_path、index_path、parameters。
    """
    preset_id = str(payload.get("id") or "").strip()
    if not PRESET_ID_RE.match(preset_id):
        raise PresetError("预设 id 只能包含小写字母、数字、下划线和连字符，且以字母或数字开头")

    display_name = str(payload.get("display_name") or "").strip()
    if not display_name:
        raise PresetError("预设名称不能为空")
    if len(display_name) > 80:
        raise PresetError("预设名称过长（最多 80 字符）")

    model_path = Path(str(payload.get("model_path") or "")).expanduser()
    if not model_path.is_file():
        raise PresetError(f"模型文件不存在：{model_path}")
    if model_path.suffix.lower() not in {".pth", ".pt"}:
        raise PresetError(f"模型文件必须是 .pth 或 .pt：{model_path}")

    index_path: Path | None = None
    raw_index = str(payload.get("index_path") or "").strip()
    if raw_index:
        index_path = Path(raw_index).expanduser()
        if not index_path.is_file():
            raise PresetError(f"索引文件不存在：{index_path}")
        if index_path.suffix.lower() != ".index":
            raise PresetError(f"索引文件必须是 .index：{index_path}")

    existing = {preset["id"] for preset in load_presets()}
    if preset_id in existing:
        raise PresetError(f"预设 id 已存在：{preset_id}")

    parameters = normalize_parameters(payload.get("parameters"))
    # 专用模型可指定独立代码目录；省略时沿用环境设置中的默认目录。
    app_root = str(payload.get("rvc_app_root") or "").strip()
    if app_root:
        for relative in ("infer/cli.py", "infer/vc/modules.py", "infer/vc/pipeline.py"):
            if not (Path(app_root) / relative).is_file():
                raise PresetError(f"RVC 代码目录缺少 {relative}：{app_root}")
    preset = {
        "id": preset_id,
        "display_name": display_name,
        "engine": "rvc",
        "description": str(payload.get("description") or "").strip() or f"用户导入的 RVC 模型（{model_path.stem}）",
        "model": {"path": str(model_path.resolve()), "sha256": sha256_file(model_path)},
        "parameters": parameters,
        "output": {"samplerate": 44100, "instrumental_boost_db": 3.0},
    }
    if index_path is not None:
        preset["index"] = {"path": str(index_path.resolve()), "sha256": sha256_file(index_path)}
    if app_root:
        preset["rvc_app_root"] = str(Path(app_root).resolve())

    USER_PRESET_DIR.mkdir(parents=True, exist_ok=True)
    target = USER_PRESET_DIR / f"{preset_id}.json"
    target.write_text(json.dumps(preset, ensure_ascii=False, indent=2), encoding="utf-8")
    preset["_source"] = str(target)
    preset["builtin"] = False
    preset["model_exists"] = True
    preset["index_exists"] = True
    return preset


def delete_preset(preset_id: str) -> None:
    """删除用户导入的预设；内置预设不可删除。"""
    for preset in load_presets():
        if preset["id"] != preset_id:
            continue
        if preset["builtin"]:
            raise PresetError("内置预设不可删除")
        source = Path(preset["_source"])
        if source.parent.resolve() != USER_PRESET_DIR.resolve():
            raise PresetError("只能删除用户导入的预设")
        source.unlink(missing_ok=True)
        return
    raise PresetError(f"预设不存在：{preset_id}")


def presets_for_engine(engine: str) -> list[dict]:
    """返回指定引擎的预设（前端下拉用）。"""
    return [preset for preset in load_presets() if preset.get("engine") == engine]


def ffmpeg_executable() -> str:
    """返回 ffmpeg 可执行文件：优先打包注入的绝对路径，其次 PATH 中的 ffmpeg。"""
    if FFMPEG is not None:
        return str(FFMPEG)
    return "ffmpeg"


def summarize_environment() -> dict:
    """收集健康检查所需的环境信息。"""
    inference_python = None
    inference_error = None
    try:
        inference_python = str(resolve_inference_python())
    except FileNotFoundError as error:
        inference_error = str(error)
    return {
        "project_root": str(PROJECT_ROOT),
        "output_root": str(OUTPUT_ROOT),
        "preset_dir": str(PRESET_DIR),
        "user_preset_dir": str(USER_PRESET_DIR),
        "rvc_app_root": str(RVC_APP_ROOT),
        "rvc_app_exists": RVC_APP_ROOT.is_dir(),
        "inference_python": inference_python,
        "inference_error": inference_error,
        "ffmpeg": ffmpeg_executable(),
        "python": sys.version.split()[0],
    }
