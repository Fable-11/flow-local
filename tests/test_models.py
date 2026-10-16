from flow.stt.models import is_model_cached


def _fake_repo(cache, repo, with_weights=True):
    snap = cache / repo / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "config.json").write_text("{}")
    if with_weights:
        (snap / "model.bin").write_bytes(b"x")


def test_cached_model_detected(tmp_path):
    _fake_repo(tmp_path, "models--Systran--faster-whisper-small")
    _fake_repo(tmp_path, "models--Systran--faster-whisper-medium", with_weights=False)
    assert is_model_cached("small", tmp_path)
    assert not is_model_cached("medium", tmp_path)  # incomplete download
    assert not is_model_cached("tiny", tmp_path)


def test_turbo_repo_naming(tmp_path):
    _fake_repo(tmp_path, "models--mobiuslabsgmbh--faster-whisper-large-v3-turbo")
    assert is_model_cached("large-v3-turbo", tmp_path)
    assert not is_model_cached("large-v3", tmp_path)


def test_missing_cache_dir(tmp_path):
    assert not is_model_cached("small", tmp_path / "nope")
