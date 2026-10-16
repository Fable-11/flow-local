"""Command-line entry point: ``python -m flow``."""

from __future__ import annotations

import argparse
import sys
import time

from flow import __version__, cli_store


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="flow", description="Flow Local dictation")
    p.add_argument("--version", action="version", version=f"flow-local {__version__}")
    p.add_argument("--background", action="store_true", help="start in the tray without the Hub")
    sub = p.add_subparsers(dest="cmd")
    t = sub.add_parser("transcribe", help="transcribe a WAV file or microphone audio")
    t.add_argument("--file", help="16-bit PCM WAV file")
    t.add_argument("--seconds", type=float, default=5.0, help="mic recording length")
    t.add_argument("--language", help="force language code (ar, en); default auto")
    t.add_argument("--model", default="auto")
    b = sub.add_parser("bench", help="measure transcription latency")
    b.add_argument("--file", help="WAV file; default 10 s of mic audio")
    sub.add_parser("doctor", help="report hardware and environment status")
    c = sub.add_parser("clean", help="run text through the cleanup pipeline")
    c.add_argument("text")
    c.add_argument("--no-llm", action="store_true")
    c.add_argument("--style", default="default")
    cli_store.add_parsers(sub)
    sub.add_parser("install-shortcuts", help="create desktop shortcuts to open and stop the app")
    sd = sub.add_parser("sound", help="play a cue sound to preview it")
    sd.add_argument("name", nargs="?", default="start", choices=["start", "stop", "error"])
    sd.add_argument("--style", default="soft", choices=["soft", "pop", "windows"])
    sd.add_argument("--volume", type=int, default=40, help="percent")
    m = sub.add_parser("mic", help="test the microphone level for a few seconds")
    m.add_argument("--seconds", type=float, default=4.0)
    sub.add_parser("run", help="start the app (default)")
    sub.add_parser("demo", help="alias of run")
    return p


def _get_audio(file: str | None, seconds: float):
    from flow.audio.capture import Recorder, load_wav

    if file:
        return load_wav(file)
    print(f"Recording {seconds:.0f}s... speak now")
    rec = Recorder()
    rec.start()
    time.sleep(seconds)
    return rec.stop()


def cmd_transcribe(args: argparse.Namespace) -> int:
    from flow.audio import enhance
    from flow.stt.engine import SttEngine, choose_model

    audio = _get_audio(args.file, args.seconds)
    prepared = enhance.prepare(audio)
    if prepared.silent:
        print(f"({enhance.quiet_hint(prepared.stats)})")
        return 1
    eng = SttEngine(choose_model(args.model))
    eng.load(allow_download=True)  # CLI use: first run downloads the model (one-time)
    text, lang, prob = eng.transcribe(prepared.audio, language=args.language)
    print(f"[{lang} {prob:.2f}] {text}")
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    from flow.stt.bench import run_bench

    print(run_bench(_get_audio(args.file, 10.0)))
    return 0


def cmd_doctor() -> int:
    """Print what Flow Local sees on this machine, to help diagnose problems."""
    import platform

    from flow.audio.capture import list_input_devices
    from flow.cleanup.llm import OllamaClient
    from flow.logging_setup import log_path
    from flow.store.db import default_db_path
    from flow.stt.engine import choose_model, cuda_available
    from flow.stt.models import is_model_cached

    print(f"Flow Local {__version__} on Python {platform.python_version()} ({platform.system()})")
    choice = choose_model()
    cached = is_model_cached(choice.name)
    print(f"GPU (CUDA) available: {cuda_available()}")
    print(f"Speech model: {choice.name} on {choice.device} ({choice.compute_type}), "
          f"{'downloaded' if cached else 'NOT downloaded (open Settings > Models)'}")
    try:
        mics = list_input_devices()
        print(f"Microphones: {len(mics)} found")
        for _i, name in mics[:6]:
            print(f"  - {name}")
    except Exception as e:  # noqa: BLE001
        print("Microphones: error:", e)
    client = OllamaClient()
    if client.available():
        print(f"Ollama: running; models: {', '.join(client.installed_models()) or 'none'}")
    else:
        print("Ollama: not running (cleanup uses built-in rules; Command Mode is unavailable)")
    from flow.hardware import detect, recommend

    hw = detect()
    rec = recommend(hw)
    print(f"Memory: {hw.ram_gb:.0f} GB. Recommended cleanup model: {rec.llm_model}")
    for note in rec.notes:
        print(f"  note: {note}")
    print(f"Database: {default_db_path()}")
    print(f"Log file: {log_path()}")
    return 0


def cmd_mic(seconds: float) -> int:
    """Record a few seconds and say whether the level is good, and what Flow Local will do."""
    import numpy as np

    from flow.audio import enhance
    from flow.audio.capture import Recorder

    print(f"Recording {seconds:.0f} s: say a sentence at the distance you normally sit...")
    rec = Recorder(keep_open=False)
    rec.start()
    time.sleep(seconds)
    audio = rec.stop()
    stats = enhance.analyze(audio)
    db = lambda v: f"{20 * np.log10(v + 1e-9):6.1f} dBFS"  # noqa: E731
    print(f"  loudest {db(stats.peak)}   speech {db(stats.speech_rms)}")
    print(f"  background noise {db(stats.noise_rms)}")
    print(f"  speech is {stats.snr_db:.0f} dB above the background noise")
    prepared = enhance.prepare(audio)
    if prepared.gain_db > 0:
        print(f"  Flow Local will boost this by +{prepared.gain_db:.0f} dB automatically")
    print(" ", enhance.describe(stats))
    return 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Arabic output must not crash cp1252 consoles
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    if args.cmd == "transcribe":
        return cmd_transcribe(args)
    if args.cmd == "bench":
        return cmd_bench(args)
    if args.cmd == "doctor":
        return cmd_doctor()
    if args.cmd == "mic":
        return cmd_mic(args.seconds)
    if args.cmd == "sound":
        import time

        from flow import sounds

        sounds.configure(True, args.volume, args.style)
        ok = sounds.play(args.name, force=True)
        time.sleep(sounds.cue_duration(args.name, args.style) + 0.2)  # let it finish
        print(f"played {args.name} ({args.style}, {args.volume}%)" if ok else "could not play")
        return 0 if ok else 1
    if args.cmd == "install-shortcuts":
        from flow.ui.shortcuts import install_shortcuts

        for lnk in install_shortcuts():
            print("created", lnk)
        return 0
    if args.cmd in ("dict", "snippet"):
        return cli_store.run(args)
    if args.cmd == "clean":
        from flow.cleanup.llm import OllamaClient
        from flow.cleanup.pipeline import CleanupPipeline
        from flow.cleanup.prompts import PromptContext

        pipe = CleanupPipeline(None if args.no_llm else OllamaClient(), use_llm=not args.no_llm)
        res = pipe.clean(args.text, PromptContext(style=args.style))
        print(res.text)
        print(f"(llm={res.used_llm} {res.note})", file=sys.stderr)
        return 0
    if args.cmd in ("demo", "run", None):
        from flow.demo import run_demo

        return run_demo(background=args.background)
    print("Flow Local: unknown command (try --help).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
