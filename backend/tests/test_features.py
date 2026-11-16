"""片段、串行队列和设备选择的行为回归测试。"""
import io
import threading
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from backend import app as api, jobs, config
from backend.engines import rvc
from backend.tests.test_api import client


def wait_done(store, ids, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if all(store.get(i)['status'] in jobs.TERMINAL_STATUSES for i in ids):
            return
        time.sleep(.02)
    pytest.fail('任务未结束')


def test_fifo_cancel_and_failure_continue(tmp_path):
    store = jobs.JobStore(tmp_path)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def runner(job, ctx):
        calls.append(job['request']['n'])
        if job['request']['n'] == 0:
            entered.set()
            release.wait(2)
            raise ValueError('fixture failure')
        return []
    items = [store.create({'n': n}) for n in range(4)]
    store.start(items[0]['id'], runner)
    assert entered.wait(1)
    for item in items[1:]:
        store.start(item['id'], runner)
    try:
        time.sleep(.1)
        assert calls == [0]
        store.cancel(items[1]['id'])
    finally:
        release.set()
    wait_done(store, [x['id'] for x in items])
    assert calls == [0, 2, 3]
    assert store.get(items[0]['id'])['status'] == 'failed'


def source_file(tmp_path, seconds=4, rate=48000):
    path = tmp_path / 'source.wav'
    sf.write(path, np.linspace(-.2, .2, int(seconds * rate)), rate, subtype='FLOAT')
    return path


def test_preview_validation_and_request(client, tmp_path, monkeypatch):
    http, store = client
    monkeypatch.setattr(store, 'start', lambda *args: None)
    payload = {'vocal_path': str(source_file(tmp_path)), 'preset_id': 'example-a'}
    for extra in ({'preview_start': 1}, {'preview_start': 2, 'preview_end': 1}, {'preview_start': 1, 'preview_end': 5}, {'device': 'dml'}):
        assert http.post('/api/jobs', json={**payload, **extra}).status_code in (400, 422)
    response = http.post('/api/jobs', json={**payload, 'preview_start': 1, 'preview_end': 3, 'device': 'cpu'})
    assert response.status_code == 200
    request = response.json()['job']['request']
    assert request['device'] == 'cpu' and request['preview_end'] == 3


def test_batch_atomic_and_comparison(client, tmp_path, monkeypatch):
    http, store = client
    monkeypatch.setattr(store, 'start', lambda *args: None)
    base = {'vocal_path': str(source_file(tmp_path)), 'preset_id': 'example-a'}
    bad = http.post('/api/jobs/batch', json={'group_kind': 'batch', 'items': [base, {**base, 'preset_id': 'missing'}]})
    assert bad.status_code in (400, 404, 422)
    assert store.list_all() == []
    body = {'group_kind': 'comparison', 'items': [base, {**base, 'preset_id': 'example-b'}]}
    result = http.post('/api/jobs/batch', json=body)
    assert result.status_code == 200, result.text
    assert len(result.json()['jobs']) == 2
    assert all(j['request']['group_id'] == result.json()['group_id'] for j in result.json()['jobs'])
    body['items'][1]['pitch_semitones'] = 2
    assert http.post('/api/jobs/batch', json=body).status_code == 400
    assert len(store.list_all()) == 2


def test_retry_keeps_original_and_snapshot(client, monkeypatch):
    http, store = client
    monkeypatch.setattr(store, 'start', lambda *args: None)
    job = store.create({'engine': 'smoke', '_preset': {'id': 'old'}, 'device': 'cpu'})
    assert http.post(f"/api/jobs/{job['id']}/retry").status_code == 409
    store.update(job['id'], status='failed')
    response = http.post(f"/api/jobs/{job['id']}/retry")
    assert response.status_code == 200
    assert response.json()['job_id'] != job['id']
    assert store.get(job['id'])['status'] == 'failed'


def test_waveform_source_selection_and_normalize(client, tmp_path):
    http, store = client
    source = source_file(tmp_path)
    result = http.post('/api/audio/waveform', json={'path': str(source)})
    assert result.status_code == 200
    assert 0 < len(result.json()['peaks']) <= 1200
    assert result.json()['frames'] == 192000
    job = store.create({'vocal_path': str(source), 'preview_start': 1., 'preview_end': 3.})
    raw = http.get(f"/api/jobs/{job['id']}/source")
    data, sr = sf.read(io.BytesIO(raw.content))
    original, _ = sf.read(source)
    assert sr == 48000 and len(data) == 96000
    np.testing.assert_allclose(data, original[48000:144000], atol=1e-7)
    normalized = http.get(f"/api/jobs/{job['id']}/source?normalize=true")
    norm, _ = sf.read(io.BytesIO(normalized.content))
    assert abs(np.sqrt(np.mean(norm**2)) - .1) < 1e-4
    assert np.max(np.abs(norm)) <= .98


def test_devices_use_inference_environment(client, monkeypatch, tmp_path):
    http, _ = client
    monkeypatch.setattr(config, 'resolve_inference_python', lambda: tmp_path / 'torch-python.exe')
    calls = []
    def probe(exe, code):
        calls.append(exe)
        return {'ok': True, 'data': {'devices': [{'id': 'cuda:0', 'label': 'NVIDIA fixture', 'kind': 'cuda'}]}}
    monkeypatch.setattr(api, '_probe_python', probe)
    result = http.get('/api/devices')
    assert result.status_code == 200
    assert [x['id'] for x in result.json()['devices']] == ['auto', 'cpu', 'cuda:0']
    assert calls == [tmp_path / 'torch-python.exe']


def test_command_passes_full_device(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'resolve_inference_python', lambda: Path('python'))
    command = rvc._build_inference_command({'parameters': config.DEFAULT_PARAMETERS, 'model': {'path': 'x'}}, {'vocal_path': 'x', 'device': 'cpu'}, tmp_path / 'out.wav')
    assert '--device' in command
    assert command[command.index('--device') + 1] == 'cpu'


@pytest.mark.parametrize('start,end', [(0., 1.25), (1.123, 2.234), (2.75, 4.)])
def test_preview_context_and_exact_timeline(tmp_path, monkeypatch, start, end):
    import json
    source = source_file(tmp_path)
    backing = tmp_path / 'backing.wav'
    sf.write(backing, np.ones((192000, 2)) * .01, 48000)
    store = jobs.JobStore(tmp_path / 'jobs')
    job = store.create({'vocal_path': str(source), 'instrumental_path': str(backing),
                        'preview_start': start, 'preview_end': end, 'device': 'cpu',
                        '_preset': {'id': 'fixture', 'display_name': 'fixture'}})
    def inference(preset, request, output, job_dir, ctx):
        info = sf.info(request['vocal_path'])
        assert abs(info.duration - (min(4, end + .5) - max(0, start - .5))) < 1 / 48000
        sf.write(output, np.arange(round(info.duration * 40000)) / 1000000., 40000, subtype='FLOAT')
        output.with_suffix('.report.json').write_text(json.dumps({'actual_device': 'cpu'}))
    monkeypatch.setattr(rvc, '_run_inference', inference)
    result = rvc.run(job, jobs.JobContext(store, job['id']))
    by_kind = {a['kind']: a for a in result}
    for kind, rate in [('vocal_40k', 40000), ('vocal_44k', 44100), ('mix', 44100)]:
        samples, actual_rate = sf.read(by_kind[kind]['path'])
        assert actual_rate == rate and len(samples) == round((end - start) * rate)
        assert np.isfinite(samples).all()
    samples, _ = sf.read(by_kind['vocal_40k']['path'])
    expected_first = round((start - max(0, start - .5)) * 40000) / 1000000
    assert abs(samples[0] - expected_first) < 1e-6
    assert store.get(job['id'])['actual_device'] == 'cpu'


def test_cancellation_terminates_silent_process(tmp_path, monkeypatch):
    import sys
    monkeypatch.setattr(rvc, '_build_inference_command', lambda *a: [sys.executable, '-c', 'import time;time.sleep(30)'])
    store = jobs.JobStore(tmp_path)
    job = store.create({})
    def runner(job, ctx):
        rvc._run_inference({}, {}, tmp_path / 'out.wav', tmp_path, ctx)
    store.start(job['id'], runner)
    time.sleep(.2)
    store.cancel(job['id'])
    # Windows taskkill /T 的进程树枚举可能需数秒，仍须早于 30 秒自然退出。
    wait_done(store, [job['id']], timeout=12)
    assert store.get(job['id'])['status'] == 'cancelled'


def test_vendor_device_configuration_cpu_cuda_and_legacy(monkeypatch):
    import ast
    import types
    import sys
    tree = ast.parse(rvc.RVC_SCRIPT.read_text(encoding='utf-8'))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'configure_inference_device']
    assert functions, '缺少生成器、HuBERT 与 RMVPE 共用的设备配置'
    torch = types.SimpleNamespace(float32='fp32', float16='fp16', version=types.SimpleNamespace(hip=None),
                                  cuda=types.SimpleNamespace(is_available=lambda: True, device_count=lambda: 2,
                                                             get_device_name=lambda n: 'NVIDIA fixture'))
    monkeypatch.setitem(sys.modules, 'torch', torch)
    namespace = {}
    exec(compile(ast.Module(body=functions, type_ignores=[]), '<device>', 'exec'), namespace)
    configure = namespace['configure_inference_device']
    cfg = types.SimpleNamespace(device='cuda:0', is_half=True, dtype='fp16', dml=True)
    configure(cfg, None)
    assert cfg.device == 'cuda:0' and cfg.dml
    configure(cfg, 'cpu')
    assert cfg.device == 'cpu' and not cfg.is_half and cfg.dtype == 'fp32' and not cfg.dml
    configure(cfg, 'cuda:1')
    assert cfg.device == 'cuda:1'
    with pytest.raises(ValueError):
        configure(cfg, 'cuda:2')
    torch.cuda.is_available = lambda: False
    configure(cfg, 'auto')
    assert cfg.device == 'cpu'


def test_float_preview_flac_export_preserves_signal(client, tmp_path):
    http, store = client
    job = store.create({})
    target = Path(job['output_dir']) / 'preview.wav'
    samples = np.array([.1, -.1, .5, -.5], dtype=np.float32)
    sf.write(target, samples, 40000, subtype='FLOAT')
    result = http.get(f"/api/jobs/{job['id']}/artifacts/preview.wav?format=flac")
    decoded, _ = sf.read(io.BytesIO(result.content))
    np.testing.assert_allclose(decoded, samples, atol=1 / 32768)


def test_cancel_during_silent_mix(tmp_path, monkeypatch):
    import sys
    silent = tmp_path / 'silent.py'
    silent.write_text('import time;time.sleep(30)', encoding='utf-8')
    monkeypatch.setattr(rvc, 'MIX_SCRIPT', silent)
    store = jobs.JobStore(tmp_path / 'jobs')
    job = store.create({})
    def runner(job, ctx):
        rvc._mix(tmp_path / 'v.wav', tmp_path / 'i.wav', tmp_path / 'o.wav', 3., ctx)
    store.start(job['id'], runner)
    time.sleep(.2)
    store.cancel(job['id'])
    wait_done(store, [job['id']], timeout=12)
    assert store.get(job['id'])['status'] == 'cancelled'


def test_waveform_streams_and_rejects_nonfinite(client, tmp_path, monkeypatch):
    http, _ = client
    source = source_file(tmp_path)
    original_read = sf.SoundFile.read
    requests = []
    def bounded_read(self, frames=-1, *args, **kwargs):
        requests.append(frames)
        assert 0 <= frames <= 65536
        return original_read(self, frames, *args, **kwargs)
    monkeypatch.setattr(sf.SoundFile, 'read', bounded_read)
    assert http.post('/api/audio/waveform', json={'path': str(source)}).status_code == 200
    assert len(requests) > 2
    sf.write(source, np.array([np.nan, 0.]), 48000, subtype='FLOAT')
    assert http.post('/api/audio/waveform', json={'path': str(source)}).status_code == 400
    sf.write(source, np.zeros(0), 48000)
    assert http.post('/api/audio/waveform', json={'path': str(source)}).status_code == 400


def test_normalized_cache_preserves_source_and_silence(client, tmp_path):
    http, store = client
    source = tmp_path / 'quiet.wav'
    sf.write(source, np.ones(10000) * 1e-5, 40000, subtype='FLOAT')
    before = source.read_bytes()
    job = store.create({'vocal_path': str(source)})
    response = http.get(f"/api/jobs/{job['id']}/source?normalize=true")
    audio, _ = sf.read(io.BytesIO(response.content))
    assert np.max(np.abs(audio)) <= 1 / 32768
    assert source.read_bytes() == before
    assert store.get(job['id'])['artifacts'] == []


def test_restarted_jobs_fail_without_automatic_execution(tmp_path):
    store = jobs.JobStore(tmp_path)
    job = store.create({'engine': 'smoke'})
    store.update(job['id'], status='running')
    restarted = jobs.JobStore(tmp_path)
    assert restarted.get(job['id'])['status'] == 'failed'
    assert restarted._worker is None


def test_comparison_preserves_separate_preset_defaults(client, tmp_path, monkeypatch):
    from copy import deepcopy
    http, store = client
    presets = config.presets_by_id()
    presets['example-a']['parameters']['index_rate'] = .1
    presets['example-b']['parameters']['index_rate'] = .3
    original = deepcopy(presets)
    monkeypatch.setattr(config, 'presets_by_id', lambda: presets)
    monkeypatch.setattr(store, 'start', lambda *a: None)
    source = source_file(tmp_path)
    response = http.post('/api/jobs/batch', json={'group_kind': 'comparison', 'items': [
        {'vocal_path': str(source), 'preset_id': key} for key in presets]})
    assert response.status_code == 200
    assert [store.get(j['id'])['request']['_preset']['parameters']['index_rate'] for j in response.json()['jobs']] == [.1, .3]
    assert presets == original


@pytest.mark.parametrize('problem', ['model', 'index', 'channels'])
def test_batch_rejects_invalid_assets_before_any_job(client, tmp_path, monkeypatch, problem):
    http, store = client
    monkeypatch.setattr(store, 'start', lambda *a: None)
    presets = config.presets_by_id()
    source = source_file(tmp_path)
    second_source = source
    if problem in ('model', 'index'):
        presets['example-b'][problem]['path'] = str(tmp_path / 'missing-asset')
    else:
        second_source = tmp_path / 'three-channel.wav'
        sf.write(second_source, np.zeros((96000, 3)), 48000)
    monkeypatch.setattr(config, 'presets_by_id', lambda: presets)
    response = http.post('/api/jobs/batch', json={'group_kind': 'batch', 'items': [
        {'vocal_path': str(source), 'preset_id': 'example-a'},
        {'vocal_path': str(second_source), 'preset_id': 'example-b'}]})
    assert response.status_code == 400, response.text
    assert store.list_all() == []
