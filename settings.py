"""Impostazioni di FOX.

Le preferenze stanno in un file JSON nella cartella di configurazione del
sistema. Le chiavi API non ci finiscono mai: vanno nel keychain tramite
`keyring`. Se il keychain non e' disponibile (succede su alcune sessioni
Linux senza DBus) le chiavi restano solo in memoria per la sessione corrente,
e FOX lo dice invece di fingere di averle salvate.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    import keyring
except Exception:                                   # pragma: no cover
    keyring = None

APP_NAME = "FOX"
KEYRING_SERVICE = "FOX"

# Chiavi usate in tutta l'app per identificare un provider
PROVIDERS = ("local", "anthropic", "openai", "nvidia")

PROVIDER_LABELS = {
    "local": "AI locale (llama.cpp)",
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "nvidia": "NVIDIA NIM",
}

DEFAULTS: dict[str, Any] = {
    # Ordine di tentativo. FOX scende al successivo se uno non risponde.
    "provider_order": ["local", "anthropic", "openai", "nvidia"],
    "model_anthropic": "claude-sonnet-5-5",
    "model_openai": "gpt-4o-mini",
    "model_nvidia": "meta/llama-3.1-8b-instruct",
    "local_model_file": "",          # nome del .gguf dentro models_dir()
    "local_context": 4096,
    "local_gpu_layers": -1,          # -1 = tutto su GPU se disponibile
    "system_prompt": (
        "Sei FOX, un assistente personale sul computer dell'utente. "
        "Rispondi in italiano, in modo diretto e breve. "
        "Se non sai qualcosa, dillo invece di inventare."
    ),
    "voice_input": True,
    "voice_output": True,
    "whisper_model": "base",         # tiny | base | small | medium
    "whisper_language": "it",
    "tts_voice": "",                 # vuoto = voce predefinita del sistema
    "hotkey": "ctrl+shift+space" if sys.platform != "darwin" else "cmd+shift+space",
    "max_history": 20,               # messaggi tenuti nel contesto
}


def _base_dir() -> Path:
    if sys.platform == "win32":
        root = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return root / APP_NAME


def config_dir() -> Path:
    d = _base_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    d = _base_dir() / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_file() -> Path:
    return config_dir() / "settings.json"


class Settings:
    """Preferenze dell'app. Una sola istanza condivisa, vedi `settings`."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = dict(DEFAULTS)
        self._memory_keys: dict[str, str] = {}
        self.keyring_available = keyring is not None
        self.load()

    # -- preferenze ---------------------------------------------------------

    def load(self) -> None:
        path = config_file()
        if not path.is_file():
            return
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print("[settings] file illeggibile, uso i valori predefiniti: %s" % exc)
            return
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key in DEFAULTS:
                    self._data[key] = value

    def save(self) -> None:
        try:
            config_file().write_text(
                json.dumps(self._data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            print("[settings] impossibile salvare: %s" % exc)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def update(self, **kwargs: Any) -> None:
        self._data.update(kwargs)
        self.save()

    # -- chiavi API ---------------------------------------------------------

    def api_key(self, provider: str) -> str:
        if provider in self._memory_keys:
            return self._memory_keys[provider]
        if keyring is None:
            return ""
        try:
            return keyring.get_password(KEYRING_SERVICE, provider) or ""
        except Exception as exc:
            print("[settings] keychain non leggibile: %s" % exc)
            self.keyring_available = False
            return ""

    def set_api_key(self, provider: str, value: str) -> bool:
        """Salva la chiave. Restituisce False se e' finita solo in memoria."""
        value = (value or "").strip()
        if keyring is not None:
            try:
                if value:
                    keyring.set_password(KEYRING_SERVICE, provider, value)
                else:
                    try:
                        keyring.delete_password(KEYRING_SERVICE, provider)
                    except Exception:
                        pass
                self._memory_keys.pop(provider, None)
                return True
            except Exception as exc:
                print("[settings] keychain non scrivibile: %s" % exc)
                self.keyring_available = False
        if value:
            self._memory_keys[provider] = value
        else:
            self._memory_keys.pop(provider, None)
        return False

    def local_model_path(self) -> Path | None:
        name = self.get("local_model_file")
        if not name:
            return None
        path = models_dir() / name
        return path if path.is_file() else None


settings = Settings()
