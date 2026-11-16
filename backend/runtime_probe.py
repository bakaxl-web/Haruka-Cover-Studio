"""在用户选择的解释器中检查依赖，不安装或升级任何软件。"""
import importlib
import json
import os
from pathlib import Path
import sys


def probe(role, app_root):
    if sys.version_info < (3, 10):
        raise RuntimeError('需要 Python 3.10 或更高版本。')
    modules = ['numpy', 'soundfile', 'scipy']
    modules += ['fastapi', 'uvicorn', 'pydantic'] if role == 'backend' else ['torch', 'librosa', 'faiss', 'parselmouth']
    missing = []
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as error:
            missing.append(f'{name}: {error}')
    if missing:
        raise RuntimeError('所选环境缺少或无法加载依赖：\n' + '\n'.join(missing))
    if role == 'backend':
        from pydantic import BaseModel
        if not hasattr(BaseModel, 'model_dump'):
            raise RuntimeError('后端需要 Pydantic 2，请选择兼容环境。')
        return f'Python {sys.version.split()[0]} · 后端依赖可加载'
    root = Path(app_root)
    if not app_root or not (root / 'infer/cli.py').is_file():
        raise RuntimeError('需要包含 infer/cli.py 的配套 RVC 代码目录。')
    # 外部 CLI 会创建缓存目录，显式放到本程序缓存中，避免写入对方的代码目录。
    cache = Path(os.environ['HARUKA_RUNTIME_CACHE'])
    for name in ['TEMP', 'TMP', 'TMPDIR', 'PIP_CACHE_DIR', 'TORCH_HOME', 'HF_HOME', 'HF_HUB_CACHE', 'HUGGINGFACE_HUB_CACHE', 'NUMBA_CACHE_DIR', 'MPLCONFIGDIR', 'PYTHONPYCACHEPREFIX']:
        os.environ[name] = str(cache / name.lower())
    sys.path.insert(0, str(root.resolve()))
    os.chdir(root)
    from infer.cli import configure_inference_seed, create_config
    from infer.vc.modules import VC
    from infer.vc.pipeline import Pipeline
    import torch
    return f'Python {sys.version.split()[0]} · PyTorch {torch.__version__} · CUDA {torch.cuda.is_available()} · 推理接口可加载（模型匹配仍需试转）'


if __name__ == '__main__':
    try:
        result = {'ok': True, 'detail': probe(sys.argv[1], sys.argv[2])}
    except Exception as error:
        result = {'ok': False, 'detail': f'{type(error).__name__}: {error}'}
    print('HARUKA_PROBE_JSON=' + json.dumps(result, ensure_ascii=False))
