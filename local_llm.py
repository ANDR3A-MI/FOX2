"""AI locale integrata: llama.cpp dentro FOX, senza Ollama ne' LM Studio.

Il modello viene caricato alla prima richiesta, non all'avvio, cosi' la
finestra compare subito. Il download dei modelli avviene dalle impostazioni
e riporta l'avanzamento con una callback.
"""

from __future__ import annotations

import threading
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

from settings import models_dir, settings

# L'import e' pigro: dentro un eseguibile PyInstaller il caricamento delle
# librerie native puo' fallire, e farlo qui all'avvio renderebbe illeggibile
# l'errore. Cosi' invece conserviamo il traceback completo e lo mostriamo
# nella diagnostica.
_Llama = None
_IMPORT_ERROR: str = ""
_import_done = False


def _load_llama():
    global _Llama, _IMPORT_ERROR, _import_done
    if _import_done:
        return _Llama
    _import_done = True
    try:
        from llama_cpp import Llama
    except Exception:
        import traceback
        _IMPORT_ERROR = traceback.format_exc()
        _Llama = None
    else:
        _Llama = Llama
    return _Llama


@dataclass(frozen=True)
class ModelInfo:
    """Un modello scaricabile dalle impostazioni."""
    key: str
    label: str
    repo: str
    filename: str
    size_mb: int
    note: str

    @property
    def url(self) -> str:
        return "https://huggingface.co/%s/resolve/main/%s" % (self.repo, self.filename)

    @property
    def path(self) -> Path:
        return models_dir() / self.filename

    @property
    def installed(self) -> bool:
        return self.path.is_file() and self.path.stat().st_size > 1024 * 1024


# Modelli piccoli, quantizzati, che girano su CPU senza GPU dedicata.
CATALOG: tuple[ModelInfo, ...] = (
    ModelInfo(
        key="qwen2.5-1.5b",
        label="Qwen2.5 1.5B Instruct",
        repo="bartowski/Qwen2.5-1.5B-Instruct-GGUF",
        filename="Qwen2.5-1.5B-Instruct-Q4_K_M.gguf",
        size_mb=1100,
        note="Il piu' leggero. Va bene su qualsiasi portatile, risposte brevi.",
    ),
    ModelInfo(
        key="qwen2.5-3b",
        label="Qwen2.5 3B Instruct",
        repo="bartowski/Qwen2.5-3B-Instruct-GGUF",
        filename="Qwen2.5-3B-Instruct-Q4_K_M.gguf",
        size_mb=2000,
        note="Buon compromesso. Consigliato se hai almeno 8 GB di RAM.",
    ),
    ModelInfo(
        key="llama3.2-3b",
        label="Llama 3.2 3B Instruct",
        repo="bartowski/Llama-3.2-3B-Instruct-GGUF",
        filename="Llama-3.2-3B-Instruct-Q4_K_M.gguf",
        size_mb=2020,
        note="Alternativa a Qwen, piu' discorsiva in italiano.",
    ),
)


def installed_models() -> list[Path]:
    """I .gguf nella cartella modelli, piu' quello aggiunto dal PC se e'
    altrove e risulta ancora al suo posto."""
    found = sorted(models_dir().glob("*.gguf"))
    external = settings.local_model_path()
    if external is not None and external.parent != models_dir():
        found.append(external)
    return found


def model_setting_value(path: Path) -> str:
    """Come salvare un modello nelle impostazioni: solo il nome se sta nella
    cartella di FOX, il percorso intero se l'utente lo tiene altrove."""
    path = Path(path)
    return path.name if path.parent == models_dir() else str(path)


def looks_like_gguf(path: Path) -> str:
    """Controllo rapido prima di accettare un file scelto dall'utente.
    Restituisce una stringa vuota se va bene, altrimenti il motivo."""
    path = Path(path)
    if not path.is_file():
        return "Il file non esiste."
    if path.suffix.lower() != ".gguf":
        return "Serve un file .gguf. I formati .bin, .safetensors e .pth non si usano qui."
    try:
        with open(path, "rb") as handle:
            magic = handle.read(4)
    except OSError as exc:
        return "Il file non e' leggibile: %s" % exc
    if magic != b"GGUF":
        return "Il file ha estensione .gguf ma non ne ha il contenuto: potrebbe essere un download interrotto."
    return ""


def available() -> bool:
    return _load_llama() is not None


def import_error() -> str:
    """Traceback completo dell'import fallito, per la diagnostica."""
    _load_llama()
    return _IMPORT_ERROR


def unavailable_reason() -> str:
    if available():
        return ""
    last = (_IMPORT_ERROR or "").strip().splitlines()
    detail = last[-1] if last else "causa sconosciuta"
    return (
        "llama.cpp non si carica in questa build. %s "
        "Il traceback completo e' in Impostazioni > Diagnostica." % detail
    )


# ---------------------------------------------------------------- download --

class DownloadCancelled(Exception):
    pass


def download_model(
    info: ModelInfo,
    on_progress: Callable[[int, int], None] | None = None,
    cancel: threading.Event | None = None,
) -> Path:
    """Scarica un modello in models_dir(). Bloccante: chiamala da un thread.

    on_progress riceve (byte scaricati, byte totali); totale 0 se ignoto.
    """
    target = info.path
    partial = target.with_suffix(target.suffix + ".part")

    request = urllib.request.Request(info.url, headers={"User-Agent": "FOX"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(partial, "wb") as handle:
                while True:
                    if cancel is not None and cancel.is_set():
                        raise DownloadCancelled()
                    chunk = response.read(1024 * 256)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if on_progress is not None:
                        on_progress(done, total)
    except DownloadCancelled:
        partial.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(
            "Download fallito (%s). Il nome del file sul repository potrebbe "
            "essere cambiato: aprilo su huggingface.co/%s e correggi CATALOG "
            "in local_llm.py." % (exc.code, info.repo)
        ) from exc
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError("Download fallito: %s" % exc) from exc

    partial.replace(target)
    return target


# ------------------------------------------------------------------ motore --

class LocalLLM:
    """Wrapper su llama.cpp. Carica il modello alla prima richiesta."""

    def __init__(self) -> None:
        self._llm = None
        self._loaded_path: Path | None = None
        self._lock = threading.Lock()

    @property
    def loaded(self) -> bool:
        return self._llm is not None

    def unload(self) -> None:
        with self._lock:
            self._llm = None
            self._loaded_path = None

    def ensure_loaded(self) -> None:
        llama_class = _load_llama()
        if llama_class is None:
            raise RuntimeError(unavailable_reason())

        path = settings.local_model_path()
        if path is None:
            found = installed_models()
            if not found:
                raise RuntimeError(
                    "Nessun modello locale installato. Aprine uno da "
                    "Impostazioni > AI locale."
                )
            path = found[0]
            settings.update(local_model_file=model_setting_value(path))

        with self._lock:
            if self._llm is not None and self._loaded_path == path:
                return
            self._llm = llama_class(
                model_path=str(path),
                n_ctx=int(settings.get("local_context", 4096)),
                n_gpu_layers=int(settings.get("local_gpu_layers", -1)),
                verbose=False,
            )
            self._loaded_path = path

    def stream(self, messages: list[dict], system: str = "") -> Iterator[str]:
        """Genera la risposta pezzo per pezzo."""
        self.ensure_loaded()
        payload = ([{"role": "system", "content": system}] if system else []) + messages

        result = self._llm.create_chat_completion(
            messages=payload,
            stream=True,
            max_tokens=1024,
            temperature=0.7,
        )
        for part in result:
            delta = part.get("choices", [{}])[0].get("delta", {})
            text = delta.get("content")
            if text:
                yield text


engine = LocalLLM()
