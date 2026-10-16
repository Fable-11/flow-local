# -*- mode: python ; coding: utf-8 -*-
"""One-folder portable build. Set FLOW_NO_CUDA=1 to leave the (huge) CUDA libraries out."""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent
datas, binaries, hiddenimports = [], [], []

for pkg in (
    "faster_whisper",
    "ctranslate2",
    "onnxruntime",
    "av",
    "tokenizers",
    "sounddevice",
    "_sounddevice_data",
):
    try:
        d, b, h = collect_all(pkg)
    except Exception as exc:  # optional packages may be absent
        print(f"spec: skipping {pkg}: {exc}")
        continue
    datas += d
    binaries += b
    hiddenimports += h

if not os.environ.get("FLOW_NO_CUDA"):
    try:
        import nvidia

        # copy every nvidia/<lib>/bin/*.dll to the same relative place inside the bundle, where
        # flow.stt.engine.add_cuda_dll_dirs() looks for them
        found = 0
        for base in map(Path, nvidia.__path__):
            for dll in base.glob("*/bin/*.dll"):
                binaries.append((str(dll), f"nvidia/{dll.parent.parent.name}/bin"))
                found += 1
        print(f"spec: bundling {found} CUDA DLLs")
    except ImportError:
        print("spec: no nvidia packages installed; building a CPU-only bundle")

icon = ROOT / "packaging" / "flow.ico"
analysis = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["flow.demo"],
    excludes=["tkinter", "pytest", "matplotlib", "PyQt5", "PyQt6", "IPython", "notebook"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

gui = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="FlowLocal",
    console=False,
    icon=str(icon) if icon.exists() else None,
)
cli = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="flow-cli",
    console=True,
    icon=str(icon) if icon.exists() else None,
)
coll = COLLECT(
    gui,
    cli,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="FlowLocal",
)
