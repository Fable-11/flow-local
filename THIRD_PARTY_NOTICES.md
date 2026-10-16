# Third-party notices

Flow Local itself is MIT licensed (see `LICENSE`). It is built on the open-source projects and
models below. None of their code or weights is stored in this repository: Python packages are
installed by `pip`, and models are downloaded by the user on first use.

## Python packages (installed by pip)

| Package | License | Used for |
|---|---|---|
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT | speech to text; ships the Silero VAD model |
| [CTranslate2](https://github.com/OpenNMT/CTranslate2) | MIT | fast inference engine under faster-whisper |
| [ONNX Runtime](https://github.com/microsoft/onnxruntime) | MIT | runs the voice-activity model |
| [PyAV](https://github.com/PyAV-Org/PyAV) | BSD-3-Clause | audio decoding (via faster-whisper) |
| [tokenizers](https://github.com/huggingface/tokenizers), [huggingface_hub](https://github.com/huggingface/huggingface_hub) | Apache-2.0 | model download and text tokens |
| [NumPy](https://numpy.org) | BSD-3-Clause | audio maths |
| [sounddevice](https://github.com/spatialaudio/python-sounddevice) | MIT | microphone capture (includes PortAudio, MIT) |
| [PySide6 / Qt for Python](https://doc.qt.io/qtforpython-6/) | LGPL-3.0 (or GPL) | the user interface |
| NVIDIA cuBLAS, cuDNN, NVRTC (`nvidia-*-cu12`) | NVIDIA proprietary license | GPU acceleration; installed by pip only if you choose the `stt` extra on an NVIDIA machine |

Development only: pytest, pytest-qt, ruff (MIT); PyInstaller (GPL-2.0 with a special exception
that allows bundling any program, including proprietary ones).

### About Qt (LGPL)
PySide6 is used as an unmodified, dynamically linked library installed from PyPI. You may
replace it with another version. If you distribute a packaged build (`scripts/build.ps1`), the
Qt libraries inside it stay under the LGPL-3.0: include its license text
(<https://www.gnu.org/licenses/lgpl-3.0.html>) and a pointer to the Qt sources
(<https://download.qt.io/>) with the build.

### About the NVIDIA libraries
A CUDA-enabled packaged build contains NVIDIA's cuBLAS/cuDNN DLLs. Redistribution is governed by
NVIDIA's license terms for those libraries. If you publish a build, read them first, or publish
the CPU-only build (`scripts\build.ps1 -NoCuda`) or just the source.

## Models (downloaded on first use, never stored in this repo)

| Model | License | Notes |
|---|---|---|
| OpenAI Whisper (via the `large-v3-turbo`, `small`, ... conversions used by faster-whisper) | MIT | speech recognition |
| Silero VAD | MIT | detects speech vs silence; bundled in faster-whisper |
| Qwen2.5-7B-Instruct (default cleanup model, through Ollama) | Apache-2.0 | |
| Qwen2.5-3B (fallback cleanup model, through Ollama) | Qwen Research License | check its terms, which may restrict commercial use |

Licenses can change between model versions: always read the license shown on each model's page
(<https://ollama.com/library/qwen2.5> and the Hugging Face model cards) before commercial use.
[Ollama](https://ollama.com) is a separate program (MIT) that you install yourself.

## Other assets
- Icons and the Flow Bar are drawn in code and are original to this project.
- The optional "Windows speech chime" sound style reads the sounds that ship with Windows from
  `C:\Windows\Media` at run time. They are not copied into this repository.
- Flow Local is an independent project. It is not affiliated with, and copies no assets from,
  any commercial dictation product.
