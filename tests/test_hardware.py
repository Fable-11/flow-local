import sys

import pytest

from flow.cleanup.llm import DEFAULT_MODEL, FALLBACK_MODEL
from flow.hardware import LOW_RAM_GB, Hardware, detect, recommend, system_ram_gb


def test_gpu_desktop_gets_the_big_setup():
    rec = recommend(Hardware(has_cuda=True, ram_gb=32))
    assert rec.llm_model == DEFAULT_MODEL and rec.memory_mode == "balanced" and not rec.notes


def test_laptop_without_a_gpu_gets_the_light_cleanup_model_and_an_explanation():
    rec = recommend(Hardware(has_cuda=False, ram_gb=16))
    assert rec.llm_model == FALLBACK_MODEL and rec.memory_mode == "balanced"
    assert any("NVIDIA" in n and "CPU" in n for n in rec.notes)


def test_small_memory_machines_unload_models_sooner():
    rec = recommend(Hardware(has_cuda=True, ram_gb=8))
    assert rec.llm_model == FALLBACK_MODEL and rec.memory_mode == "low"
    assert any("8 GB" in n for n in rec.notes)
    assert recommend(Hardware(has_cuda=False, ram_gb=LOW_RAM_GB)).memory_mode == "balanced"


def test_unknown_memory_is_not_treated_as_low():
    rec = recommend(Hardware(has_cuda=True, ram_gb=0.0))
    assert rec.llm_model == DEFAULT_MODEL and rec.memory_mode == "balanced"


def test_recommendation_maps_to_valid_settings():
    from flow.config import MEMORY_MODES, settings_from_dict

    for hw in (Hardware(True, 32), Hardware(False, 16), Hardware(False, 4)):
        s = settings_from_dict(recommend(hw).as_settings())
        assert s.memory_mode in MEMORY_MODES and s.llm_model


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_detect_reports_real_numbers_on_this_machine():
    assert system_ram_gb() > 1
    hw = detect()
    assert isinstance(hw.has_cuda, bool) and hw.ram_gb > 1
