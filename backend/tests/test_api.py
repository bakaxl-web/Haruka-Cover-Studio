"""后端 API 测试：健康检查、预设、任务生命周期与取消。"""
from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module
from backend import config
from backend import jobs as jobs_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    store = jobs_module.JobStore(tmp_path)
    monkeypatch.setattr(jobs_module, "store", store)
    # 用户预设写入临时目录，避免测试污染真实的 %APPDATA%
    monkeypatch.setattr(config, "USER_PRESET_DIR", tmp_path / "user-presets")
    # 测试自建预设，不依赖开发机模型库；公开源码无需携带私人预设。
    import json
    preset_dir = tmp_path / "builtin-presets"
    preset_dir.mkdir()
    for preset_id in ("example-a", "example-b"):
        preset = {"id": preset_id, "display_name": preset_id, "engine": "rvc",
                  "model": {"path": str(tmp_path / "voice.pth")},
                  "parameters": dict(config.DEFAULT_PARAMETERS)}
        (preset_dir / f"{preset_id}.json").write_text(json.dumps(preset), encoding="utf-8")
    monkeypatch.setattr(config, "PRESET_DIR", preset_dir)
    return TestClient(app_module.app), store


def test_import_preserves_dedicated_runtime_and_rejects_missing_code(client, tmp_path):
    http, _store = client
    model = tmp_path / 'voice.pth'
    model.write_bytes(b'test-model')
    app_root = tmp_path / 'dedicated-app'
    payload = {'id': 'dedicated', 'display_name': '专用声线', 'model_path': str(model), 'rvc_app_root': str(app_root)}
    assert http.post('/api/presets', json=payload).status_code == 400
    for relative in ['infer/cli.py', 'infer/vc/modules.py', 'infer/vc/pipeline.py']:
        target = app_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('# fixture', encoding='utf-8')
    response = http.post('/api/presets', json=payload)
    assert response.status_code == 200
    preset = next(item for item in config.load_presets() if item['id'] == 'dedicated')
    assert preset['rvc_app_root'] == str(app_root.resolve())


def test_health(client):
    http, _store = client
    response = http.get("/api/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["environment"]["preset_dir"].endswith("presets")


def test_bundled_preset_paths_follow_package_location(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(config, 'USER_PRESET_DIR', tmp_path / 'empty-user')
    for folder in ('first-location', 'moved-location'):
        root = tmp_path / folder
        preset_dir = root / 'backend' / 'presets'
        preset_dir.mkdir(parents=True)
        model = root / 'model-bundle' / 'weights' / 'voice.pth'
        model.parent.mkdir(parents=True)
        model.write_bytes(b'weight')
        index = model.with_suffix('.index')
        index.write_bytes(b'index')
        preset = {'id': 'bundled-test', 'model': {'path': 'model-bundle/weights/voice.pth'}, 'index': {'path': 'model-bundle/weights/voice.index'}, 'rvc_app_root': 'model-bundle/apps/e400'}
        saved = json.dumps(preset)
        target = preset_dir / 'voice.json'
        target.write_text(saved, encoding='utf-8')
        monkeypatch.setattr(config, 'PROJECT_ROOT', root)
        monkeypatch.setattr(config, 'PRESET_DIR', preset_dir)
        loaded = config.load_presets()[0]
        assert loaded['model_exists'] and loaded['index_exists']
        assert loaded['model']['path'] == str(model.resolve())
        assert loaded['rvc_app_root'] == str((root / 'model-bundle/apps/e400').resolve())
        assert target.read_text(encoding='utf-8') == saved


def test_presets_listing(client):
    http, _store = client
    response = http.get("/api/presets")
    assert response.status_code == 200
    presets = response.json()
    ids = {preset["id"] for preset in presets}
    assert ids == {"example-a", "example-b"}


def test_unknown_preset_rejected(client):
    http, _store = client
    response = http.post(
        "/api/jobs",
        json={"vocal_path": "x.wav", "instrumental_path": "y.wav", "preset_id": "missing"},
    )
    assert response.status_code in (400, 404)


def test_smoke_job_reaches_success(client, tmp_path):
    http, store = client
    # smoke 引擎不读取音频，这里用两个占位路径即可
    vocal = tmp_path / "vocal.wav"
    instrumental = tmp_path / "instrumental.wav"
    vocal.write_bytes(b"")
    instrumental.write_bytes(b"")
    response = http.post(
        "/api/jobs",
        json={
            "vocal_path": str(vocal),
            "instrumental_path": str(instrumental),
            "preset_id": "smoke",
            "engine": "smoke",
        },
    )
    assert response.status_code == 200, response.text
    job_id = response.json()["job_id"]

    deadline = time.time() + 20
    status = None
    while time.time() < deadline:
        status = http.get(f"/api/jobs/{job_id}").json()
        if status["status"] in ("succeeded", "failed", "cancelled"):
            break
        time.sleep(0.2)
    assert status is not None
    assert status["status"] == "succeeded", status
    assert status["progress"] == 1.0
    assert (tmp_path / job_id / "job.json").is_file()
    assert (tmp_path / job_id / "job.log").is_file()


def test_cancel_queued_job(client, tmp_path):
    http, store = client
    job = store.create({"vocal_path": "x", "instrumental_path": "y", "preset_id": "smoke"})
    response = http.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


def _make_model_files(tmp_path):
    """构造假的模型与索引文件，只为通过文件存在性校验。"""
    model = tmp_path / "my-voice.pth"
    model.write_bytes(b"fake-model-bytes")
    index = tmp_path / "my-voice.index"
    index.write_bytes(b"fake-index-bytes")
    return model, index


def test_import_preset_writes_user_preset(client, tmp_path):
    http, _store = client
    model, index = _make_model_files(tmp_path)
    response = http.post(
        "/api/presets",
        json={
            "id": "my-voice",
            "display_name": "我的声线",
            "model_path": str(model),
            "index_path": str(index),
            "parameters": {"index_rate": 0.5},
        },
    )
    assert response.status_code == 200, response.text
    created = response.json()
    assert created["id"] == "my-voice"
    assert created["builtin"] is False
    assert created["parameters"]["index_rate"] == 0.5
    # 未指定的参数回落到默认值
    assert created["parameters"]["f0_method"] == config.DEFAULT_PARAMETERS["f0_method"]

    listed = http.get("/api/presets").json()
    imported = [preset for preset in listed if preset["id"] == "my-voice"]
    assert imported and imported[0]["model_exists"] is True
    assert imported[0]["index_exists"] is True


def test_import_preset_validation(client, tmp_path):
    http, _store = client
    # 模型不存在
    missing = http.post(
        "/api/presets",
        json={"id": "missing-model", "display_name": "x", "model_path": str(tmp_path / "nope.pth")},
    )
    assert missing.status_code == 400
    # 非法 id
    model, _index = _make_model_files(tmp_path)
    bad_id = http.post(
        "/api/presets",
        json={"id": "Bad Id!", "display_name": "x", "model_path": str(model)},
    )
    assert bad_id.status_code == 400
    # 参数越界
    out_of_range = http.post(
        "/api/presets",
        json={
            "id": "bad-params",
            "display_name": "x",
            "model_path": str(model),
            "parameters": {"index_rate": 5.0},
        },
    )
    assert out_of_range.status_code == 400


def test_delete_preset_rules(client, tmp_path):
    http, _store = client
    model, _index = _make_model_files(tmp_path)
    assert (
        http.post(
            "/api/presets",
            json={"id": "temp-voice", "display_name": "临时", "model_path": str(model)},
        ).status_code
        == 200
    )
    assert http.delete("/api/presets/temp-voice").status_code == 200
    assert all(preset["id"] != "temp-voice" for preset in http.get("/api/presets").json())
    # 内置预设不可删除
    assert http.delete("/api/presets/haruka-v6b1d-e400").status_code == 400


def test_diagnostics_groups(client):
    http, _store = client
    response = http.get("/api/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    group_ids = [group["id"] for group in payload["groups"]]
    assert group_ids == ["runtime", "gpu", "models", "storage"]
    assert payload["checked_at"]


def test_separation_presets_removed(client):
    """旧分离入口不再提供服务。"""
    http, _store = client
    assert http.get("/api/separation-presets").status_code == 404


def test_separation_job_validates_layers(client):
    """分离任务的各层校验：缺字段 400、未知预设 404、未知 kind 400。"""
    http, _store = client
    assert http.post("/api/jobs", json={"kind": "separation"}).status_code == 400
    assert http.post("/api/jobs", json={"kind": "separation", "input_path": "a.wav"}).status_code == 400
    assert (
        http.post(
            "/api/jobs",
            json={"kind": "separation", "input_path": "a.wav", "separation_preset_id": "nope"},
        ).status_code
        == 400
    )
    assert http.post("/api/jobs", json={"kind": "weird"}).status_code == 400


def test_vocal_only_and_task_parameters(client, tmp_path, monkeypatch):
    """任务参数只影响本次转换，不覆盖已有模型预设。"""
    import numpy as np
    import soundfile as sf
    from copy import deepcopy
    http, store = client
    vocal = tmp_path / "vocal.wav"
    sf.write(vocal, np.zeros(4410), 44100)
    preset = deepcopy(config.load_presets()[0])
    original = deepcopy(preset)
    monkeypatch.setattr(config, "presets_by_id", lambda: {preset["id"]: preset})
    monkeypatch.setattr(store, "start", lambda *args: None)
    response = http.post("/api/jobs", json={"vocal_path": str(vocal), "preset_id": preset["id"],
        "pitch_semitones": 3, "index_rate": 0, "protect": 0.2, "vocal_gain_db": -2})
    assert response.status_code == 200, response.text
    job = store.get(response.json()["job_id"])
    assert job["request"]["instrumental_path"] is None
    assert job["request"]["pitch_semitones"] == 3
    assert job["request"]["_preset"]["parameters"]["index_rate"] == 0
    assert job["request"]["_preset"]["parameters"]["protect"] == 0.2
    assert job["request"]["vocal_gain_db"] == -2
    assert preset == original
    assert http.post("/api/jobs", json={"kind": "oneshot"}).status_code == 400
    assert http.post("/api/jobs", json={"pitch_semitones": 13}).status_code == 422


def test_vocal_only_contract(tmp_path):
    import numpy as np
    import soundfile as sf
    from backend.contracts import validate_inputs, ContractError
    vocal = tmp_path / "vocal.wav"
    sf.write(vocal, np.ones(1000) * 0.1, 40000)
    result = validate_inputs(vocal, None)
    assert result["vocal"]["frames"] == 1000
    assert result["instrumental"] is None
    sf.write(vocal, np.full(1000, np.nan), 40000, subtype="FLOAT")
    with pytest.raises(ContractError):
        validate_inputs(vocal, None)


def test_history_reload_and_audio_export(client, tmp_path):
    import io
    import numpy as np
    import soundfile as sf
    from pathlib import Path
    http, store = client
    source = tmp_path / "source.wav"
    samples = np.arange(1000, dtype=np.int16)
    sf.write(source, samples, 40000, subtype="PCM_16")
    job = store.create({"vocal_path": str(source)})
    output = Path(job["output_dir"]) / "vocal.wav"
    sf.write(output, samples, 40000, subtype="PCM_16")
    store.update(job["id"], status="succeeded", artifacts=[{"name": output.name, "path": str(output), "kind": "vocal_40k", "size": output.stat().st_size}])
    restored = jobs_module.JobStore(tmp_path)
    assert restored.get(job["id"])["status"] == "succeeded"
    assert http.get(f"/api/jobs/{job['id']}/source").content == source.read_bytes()
    response = http.get(f"/api/jobs/{job['id']}/artifacts/vocal.wav?format=flac")
    assert response.status_code == 200
    assert response.content[:4] == b"fLaC"
    audio, rate = sf.read(io.BytesIO(response.content), dtype="int16")
    assert rate == 40000
    np.testing.assert_array_equal(audio, samples)


def test_inference_command_contains_pitch(tmp_path):
    from backend.engines.rvc import _build_inference_command
    preset = config.load_presets()[0]
    command = _build_inference_command(preset, {"vocal_path": "source.wav", "pitch_semitones": -3}, tmp_path / "output.wav")
    assert command[command.index("--pitch-semitones") + 1] == "-3"


@pytest.mark.parametrize("with_backing", [False, True])
def test_rvc_outputs_with_optional_backing(tmp_path, monkeypatch, with_backing):
    """真实重采样与混音，只有 GPU 推理替换为固定已知音频。"""
    import json
    import numpy as np
    import soundfile as sf
    from backend.engines import rvc
    vocal = tmp_path / "input.wav"
    backing = tmp_path / "backing.wav"
    sf.write(vocal, np.ones(4410) * 0.1, 44100)
    sf.write(backing, np.ones((4410, 2)) * 0.02, 44100)
    store = jobs_module.JobStore(tmp_path / "outputs")
    job = store.create({"vocal_path": str(vocal), "instrumental_path": str(backing) if with_backing else None,
        "_preset": {"id": "test", "display_name": "test"}, "pitch_semitones": 0})
    def inference(preset, request, output, job_dir, ctx):
        sf.write(output, np.ones(4000) * 0.1, 40000)
        output.with_suffix(".report.json").write_text(json.dumps({"test": True}))
    monkeypatch.setattr(rvc, "_run_inference", inference)
    result = rvc.run(job, jobs_module.JobContext(store, job["id"]))
    assert len(result) == (6 if with_backing else 4)
    assert any(a["kind"] == "mix" for a in result) == with_backing
    for artifact in result:
        if artifact["kind"] in ("vocal_44k", "mix"):
            audio, rate = sf.read(artifact["path"])
            assert rate == 44100 and len(audio) == 4410 and np.isfinite(audio).all()
