"""Diagnostica: stato reale di ogni componente, in una stringa sola.

Serve in due posti. Nelle impostazioni, per capire perche' qualcosa non
funziona sul computer dell'utente. E nella pipeline di build, lanciando
l'eseguibile appena compilato con --selftest: cosi' l'errore compare nel log
di GitHub Actions invece che dopo il download, su una macchina che non
possiamo ispezionare.
"""

from __future__ import annotations

import platform
import shutil
import sys
import traceback

MODULES = (
    "numpy", "PySide6", "sounddevice", "keyring", "pynput",
    "anthropic", "openai", "ctranslate2", "faster_whisper",
    "tokenizers", "huggingface_hub", "llama_cpp",
)


def _mark(ok: bool) -> str:
    return "OK  " if ok else "NO  "


def _try_import(name: str) -> tuple[bool, str]:
    """Importa e restituisce (riuscito, dettaglio). Il dettaglio e' il
    percorso del modulo se funziona, il traceback se no."""
    try:
        module = __import__(name)
    except Exception:
        return False, traceback.format_exc(limit=3).strip()
    where = getattr(module, "__file__", "modulo incorporato")
    version = getattr(module, "__version__", "")
    return True, "%s%s" % (where, (" v" + version) if version else "")


def report() -> str:
    lines: list[str] = []

    lines.append("FOX — diagnostica")
    lines.append("Sistema: %s %s (%s)" % (
        platform.system(), platform.release(), platform.machine()))
    lines.append("Python: %s" % sys.version.split()[0])
    frozen = bool(getattr(sys, "frozen", False))
    lines.append("Eseguibile compilato: %s" % frozen)
    if frozen:
        lines.append("Cartella del pacchetto: %s" % getattr(sys, "_MEIPASS", "?"))
    lines.append("")

    lines.append("MODULI")
    for name in MODULES:
        ok, detail = _try_import(name)
        lines.append("%s%s" % (_mark(ok), name))
        for line in detail.splitlines():
            lines.append("      %s" % line)
    lines.append("")

    # Da qui in poi si importano i moduli di FOX, che a loro volta importano
    # i pacchetti qui sopra: se uno e' rotto, l'elenco precedente lo ha gia'
    # detto e questa parte puo' fallire senza perdere informazioni.
    lines.append("AI LOCALE")
    try:
        import local_llm
        from settings import settings

        ok_llama = local_llm.available()
        lines.append("%sllama.cpp" % _mark(ok_llama))
        if not ok_llama:
            for line in (local_llm.import_error() or "").strip().splitlines():
                lines.append("      %s" % line)
        found = local_llm.installed_models()
        lines.append("%s%d modello/i trovato/i" % (_mark(bool(found)), len(found)))
        for path in found:
            lines.append("      %s" % path)
        lines.append("    attivo: %s" % (settings.local_model_path() or "nessuno"))
    except Exception:
        lines.append(traceback.format_exc().strip())
    lines.append("")

    lines.append("VOCE")
    try:
        import voice
        from settings import settings

        mic = voice.microphone_problem()
        lines.append("%smicrofono%s" % (_mark(not mic), "" if not mic else ": " + mic))
        for device in voice.input_devices():
            lines.append("      %s" % device)
        whisper = voice.whisper_problem()
        lines.append("%sfaster-whisper%s" % (
            _mark(not whisper), "" if not whisper else ": " + whisper))
        lines.append("    modello Whisper: %s" % settings.get("whisper_model"))
        tts = voice.tts_problem()
        lines.append("%ssintesi vocale%s" % (
            _mark(not tts), "" if not tts else ": " + tts))
        voices = voice.list_voices()
        lines.append("    %d voci di sistema" % len(voices))
        if voices:
            lines.append("      %s" % ", ".join(voices[:6]))
    except Exception:
        lines.append(traceback.format_exc().strip())
    lines.append("")

    lines.append("PROVIDER")
    try:
        import providers
        for provider in providers.router.order():
            ready = provider.ready()
            lines.append("%s%s%s" % (
                _mark(ready), provider.label,
                "" if ready else " — " + provider.why_not_ready()))
    except Exception:
        lines.append(traceback.format_exc().strip())
    lines.append("")

    lines.append("ALTRO")
    lines.append("%sffmpeg nel PATH" % _mark(bool(shutil.which("ffmpeg"))))
    try:
        from settings import config_dir
        lines.append("    impostazioni: %s" % config_dir())
    except Exception as exc:
        lines.append("    impostazioni non accessibili: %s" % exc)

    return "\n".join(lines)


def run_selftest() -> int:
    """Scrive la diagnostica su file e la stampa.

    L'eseguibile e' compilato senza console, quindi su Windows lo stdout non
    arriva da nessuna parte: il file e' l'unico modo per leggerlo dal log
    della pipeline.
    """
    text = report()
    try:
        with open("fox-selftest.txt", "w", encoding="utf-8") as handle:
            handle.write(text)
    except OSError as exc:
        text += "\n\n(impossibile scrivere fox-selftest.txt: %s)" % exc
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(run_selftest())
