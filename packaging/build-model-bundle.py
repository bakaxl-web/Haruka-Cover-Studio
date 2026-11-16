"""按本机清单构建可迁移的模型资源包；清单本身不得提交到 Git。"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def digest(file):
    with file.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(spec, output):
    if output.exists():
        raise FileExistsError(f'输出已存在，请使用新的版本目录：{output}')
    output.mkdir(parents=True)
    files = []

    def copy(source, relative, role, expected=None):
        source = Path(source)
        fingerprint = digest(source)
        if expected and fingerprint != expected:
            raise ValueError(f'源文件 SHA-256 不匹配：{source}')
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if digest(target) != fingerprint:
            raise ValueError(f'复制校验失败：{relative}')
        files.append({'path': relative.as_posix(), 'role': role, 'bytes': target.stat().st_size, 'sha256': fingerprint})

    def write(relative, value, role):
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        files.append({'path': relative.as_posix(), 'role': role, 'bytes': target.stat().st_size, 'sha256': digest(target)})

    for app_id, source in spec['apps'].items():
        source = Path(source)
        dest = Path('apps') / app_id
        # 仅复制推理实际依赖的源码与配置，不带环境、训练日志、数据集或其他声线。
        for directory in ('infer', 'configs', 'i18n', 'tools'):
            for file in sorted((source / directory).rglob('*')):
                relative = file.relative_to(source).as_posix()
                if directory == 'tools' and relative not in ('tools/__init__.py', 'tools/file_io.py', 'tools/cuda_graph.py', 'tools/progress.py'):
                    continue
                if relative == 'configs/config.json':
                    continue
                if file.is_file() and file.suffix.lower() in ('.py', '.json') and '__pycache__' not in file.parts:
                    copy(file, dest / file.relative_to(source), 'inference_code')
        for name in ('LICENSE', 'MIT协议暨相关引用库协议'):
            if (source / name).is_file():
                copy(source / name, dest / name, 'license')
        for file in sorted((source / 'assets/hubert_base').iterdir()):
            if file.is_file() and file.suffix.lower() in ('.json', '.bin', '.safetensors', '.txt', '.md'):
                copy(file, dest / 'assets/hubert_base' / file.name, 'hubert')
        copy(source / 'assets/rmvpe/rmvpe.pt', dest / 'assets/rmvpe/rmvpe.pt', 'rmvpe')
        print(f'App copied: {app_id}', flush=True)

    summary = []
    for model in spec['models']:
        preset = model['preset']
        weight_path = Path('weights') / model['weight_name']
        copy(model['weight_source'], weight_path, 'inference_weight', model['weight_sha256'])
        preset['model'] = {'path': f'model-bundle/{weight_path.as_posix()}', 'sha256': model['weight_sha256']}
        preset['rvc_app_root'] = f'model-bundle/apps/{model["app"]}'
        if model.get('index_source'):
            index_path = Path('indices') / model['index_name']
            copy(model['index_source'], index_path, 'index', model['index_sha256'])
            preset['index'] = {'path': f'model-bundle/{index_path.as_posix()}', 'sha256': model['index_sha256']}
        write(Path('presets') / f'{preset["id"]}.json', preset, 'preset')
        summary.append({'id': preset['id'], 'display_name': preset['display_name'], 'quality_status': model['quality_status'], 'app': model['app']})
        print(f'Model verified: {preset["id"]}', flush=True)
    write(Path('default-runtime.json'), {'rvc_app_root': f'apps/{spec["default_app"]}'}, 'runtime_default')
    manifest = {'schema_version': 1, 'models': summary, 'files': files, 'bytes': sum(item['bytes'] for item in files)}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('.build/model-bundle'))
    args = parser.parse_args()
    result = build(json.loads(args.spec.read_text(encoding='utf-8')), args.output.resolve())
    print(json.dumps({'models': len(result['models']), 'files': len(result['files']), 'bytes': result['bytes']}))
