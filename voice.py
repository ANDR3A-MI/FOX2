"""Voce: microfono, trascrizione offline, sintesi vocale di sistema.

La trascrizione usa faster-whisper invece di openai-whisper: stesso modello,
nessuna dipendenza da torch, che da solo farebbe crescere l'installer di oltre
un gigabyte.

La sintesi vocale non usa librerie: chiama il sintetizzatore gia' presente nel
sistema operativo. Su Windows passa da PowerShell e System.Speech, su macOS dal
comando `say`. Cosi' funziona offline e parla italiano se la voce e' installata.
"""

from __future__ import annotations

import queue
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path
from typing import Callable

from settings import settings

try:
    import numpy as np
except Exception:                                   # pragma: no cover
    np = None

try:
    import sounddevice as sd
except Exception:                                   # pragma: no cover
    sd = None

SAMPLE_RATE = 16000
SILENCE_RMS = 0.012          # soglia sotto la quale si considera silenzio
SILENCE_SECONDS = 1.1        # quanto silenzio serve per smettere di ascoltare
MIN_SECONDS = 0.6            # sotto questa durata si ignora: e' un rumore
MAX_SECONDS = 30.0


def microphone_available() -> bool:
    return sd is not None and np is not None


def microphone_problem() -> str:
    if np is None:
        return "numpy non e' installato."
    if sd is None:
        return "sounddevice non e' installato o non trova un microfono."
    return ""


# ------------------------------------------------------------ registrazione --

class Recorder:
    """Registra finche' l'utente parla, poi si ferma da solo.

    Non c'e' un pulsante di stop: l'endpointing e' sul livello audio, come
    descritto nel README ("FOX smette di ascoltare da solo").
    """

    def __init__(self) -> None:
        self._stop = threading.Event()

    def cancel(self) -> None:
        self._stop.set()

    def record(self, on_level: Callable[[float], None] | None = None) -> "np.ndarray | None":
        if not microphone_available():
            raise RuntimeError(microphone_problem())

        self._stop.clear()
        frames: list = []
        blocks: "queue.Queue" = queue.Queue()

        def callback(indata, _frames, _time, status):
            if status:
                print("[voice] %s" % status)
            blocks.put(indata.copy())

        silence_for = 0.0
        total = 0.0
        heard_voice = False

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=int(SAMPLE_RATE * 0.05), callback=callback,
        ):
            while not self._stop.is_set() and total < MAX_SECONDS:
                try:
                    block = blocks.get(timeout=0.5)
                except queue.Empty:
                    continue

                frames.append(block)
                duration = len(block) / SAMPLE_RATE
                total += duration

                rms = float(np.sqrt(np.mean(np.square(block))))
                if on_level is not None:
                    on_level(min(1.0, rms * 14.0))

                if rms >= SILENCE_RMS:
                    heard_voice = True
                    silence_for = 0.0
                elif heard_voice:
                    silence_for += duration
                    if silence_for >= SILENCE_SECONDS:
                        break

        if not frames or total < MIN_SECONDS or not heard_voice:
            return None
        return np.concatenate(frames, axis=0).flatten()


def write_wav(audio: "np.ndarray", path: Path) -> Path:
    clipped = np.clip(audio, -1.0, 1.0)
    pcm = (clipped * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes(pcm.tobytes())
    return path


# -------------------------------------------------------------- Whisper ----

class Transcriber:
    """Riconoscimento vocale offline. Il modello si carica alla prima frase."""

    def __init__(self) -> None:
        self._model = None
        self._model_name = ""
        self._lock = threading.Lock()

    def ensure_loaded(self) -> None:
        name = settings.get("whisper_model", "base")
        with self._lock:
            if self._model is not None and self._model_name == name:
                return
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "faster-whisper non e' installato: il riconoscimento vocale "
                    "non e' disponibile in questa build."
                ) from exc
            self._model = WhisperModel(name, device="auto", compute_type="int8")
            self._model_name = name

    def transcribe(self, audio: "np.ndarray") -> str:
        self.ensure_loaded()
        language = settings.get("whisper_language") or None
        segments, _info = self._model.transcribe(
            audio, language=language, vad_filter=True, beam_size=1,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()


transcriber = Transcriber()


# ------------------------------------------------------- sintesi vocale ----

class Speaker:
    """Parla con la voce del sistema. Una frase alla volta, interrompibile."""

    def __init__(self) -> None:
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def stop(self) -> None:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                except Exception:
                    pass
            self._process = None

    def say(self, text: str) -> None:
        text = (text or "").strip()
        if not text or not settings.get("voice_output", True):
            return
        self.stop()
        voice = (settings.get("tts_voice") or "").strip()

        try:
            if sys.platform == "darwin":
                command = ["say"]
                if voice:
                    command += ["-v", voice]
                command.append(text)
                self._spawn(command)

            elif sys.platform == "win32":
                # Il testo passa da un file temporaneo: cosi' apici e accenti
                # non vengono mangiati dall'escaping di PowerShell.
                handle = tempfile.NamedTemporaryFile(
                    "w", suffix=".txt", delete=False, encoding="utf-8"
                )
                handle.write(text)
                handle.close()
                select = (
                    "$s.SelectVoice('%s');" % voice.replace("'", "''") if voice else ""
                )
                script = (
                    "Add-Type -AssemblyName System.Speech;"
                    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                    + select +
                    "$t = Get-Content -Raw -Encoding UTF8 '%s';" % handle.name +
                    "$s.Speak($t);"
                )
                self._spawn([
                    "powershell", "-NoProfile", "-NonInteractive", "-Command", script
                ], hide_window=True)

            else:
                self._spawn(["espeak-ng", "-v", voice or "it", text])

        except FileNotFoundError:
            print("[voice] nessun sintetizzatore vocale disponibile su questo sistema")
        except Exception as exc:
            print("[voice] sintesi fallita: %s" % exc)

    def _spawn(self, command: list[str], hide_window: bool = False) -> None:
        kwargs: dict = {}
        if hide_window and sys.platform == "win32":
            info = subprocess.STARTUPINFO()
            info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            kwargs["startupinfo"] = info
            kwargs["creationflags"] = 0x08000000      # CREATE_NO_WINDOW
        with self._lock:
            self._process = subprocess.Popen(
                command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kwargs
            )


speaker = Speaker()


def list_voices() -> list[str]:
    """Nomi delle voci installate, per il menu nelle impostazioni."""
    try:
        if sys.platform == "darwin":
            out = subprocess.run(
                ["say", "-v", "?"], capture_output=True, text=True, timeout=5
            ).stdout
            return [line.split()[0] for line in out.splitlines() if line.strip()]
        if sys.platform == "win32":
            script = (
                "Add-Type -AssemblyName System.Speech;"
                "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                ".GetInstalledVoices() | %{$_.VoiceInfo.Name}"
            )
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command", script],
                capture_output=True, text=True, timeout=10,
            ).stdout
            return [line.strip() for line in out.splitlines() if line.strip()]
    except Exception as exc:
        print("[voice] elenco voci non disponibile: %s" % exc)
    return []
