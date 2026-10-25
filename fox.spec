# -*- mode: python ; coding: utf-8 -*-
#
# PyInstaller spec per F.O.X. — funziona su Windows e macOS con lo stesso file.
#   pyinstaller fox.spec --noconfirm
#
# Produce:
#   Windows -> dist/FOX/FOX.exe  (cartella, poi impacchettata da installer.iss)
#   macOS   -> dist/FOX.app      (poi trasformata in .dmg dal workflow)

import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

IS_WIN = sys.platform.startswith("win")
IS_MAC = sys.platform == "darwin"

binaries = []
datas = []
hiddenimports = []


def try_collect(label, fn, *args, **kwargs):
    """Raccoglie senza far fallire il build se il pacchetto non c'è."""
    try:
        out = fn(*args, **kwargs)
        print("[fox.spec] %s: %d elementi" % (label, len(out)))
        return out
    except Exception as exc:                      # pacchetto assente o non installabile
        print("[fox.spec] %s non raccolto: %s" % (label, exc))
        return []


# --- AI locale -------------------------------------------------------------
# Solo collect_dynamic_libs, MAI collect_data_files: quest'ultimo raccoglie gli
# stessi .dll/.dylib anche come dati, e la doppia copia fa fallire l'import con
# "cannot load module more than once per process".
binaries += try_collect("llama_cpp (binari)", collect_dynamic_libs, "llama_cpp")
hiddenimports += ["llama_cpp", "diskcache"]

# --- Riconoscimento vocale -------------------------------------------------
# faster-whisper usa ctranslate2, che è un'estensione C con librerie native.
binaries += try_collect("ctranslate2 (binari)", collect_dynamic_libs, "ctranslate2")
hiddenimports += ["ctranslate2"]
for pkg in ("faster_whisper", "tokenizers", "huggingface_hub"):
    datas += try_collect("%s (dati)" % pkg, collect_data_files, pkg)
    hiddenimports += try_collect("%s (moduli)" % pkg, collect_submodules, pkg)

# --- Audio: portaudio è una DLL/dylib separata, in un pacchetto a parte -----
binaries += try_collect("sounddevice", collect_dynamic_libs, "sounddevice")
datas += try_collect("sounddevice (dati)", collect_data_files, "sounddevice")
datas += try_collect("_sounddevice_data", collect_data_files, "_sounddevice_data")
hiddenimports += ["_sounddevice_data"]

# --- Keychain: i backend si importano dinamicamente, PyInstaller non li vede ---
hiddenimports += try_collect("keyring", collect_submodules, "keyring.backends")

# --- Provider online ---
hiddenimports += ["anthropic", "openai", "httpx", "certifi"]

# --- Scorciatoia globale ---
hiddenimports += try_collect("pynput", collect_submodules, "pynput")

# --- Moduli di FOX ---
hiddenimports += [
    "island", "providers", "local_llm", "voice", "settings", "settings_ui",
]

# --- Risorse dell'app (icone, font, shader): incluse solo se esistono ---
for folder in ("assets", "resources"):
    if os.path.isdir(folder):
        datas.append((folder, folder))


def first_existing(*paths):
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return None


ICON = first_existing(
    os.path.join("assets", "fox.ico") if IS_WIN else os.path.join("assets", "fox.icns"),
    "fox.ico" if IS_WIN else "fox.icns",
)


a = Analysis(
    ["app.py"],
    pathex=["."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        "tkinter", "matplotlib", "PyQt5", "PyQt6", "pytest",
        "IPython", "notebook", "pandas",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FOX",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # UPX rompe le DLL native di llama.cpp
    console=False,             # nessuna finestra nera all'avvio
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FOX",
)

if IS_MAC:
    app = BUNDLE(
        coll,
        name="FOX.app",
        icon=ICON,
        bundle_identifier="com.fox.assistant",
        info_plist={
            "CFBundleName": "FOX",
            "CFBundleDisplayName": "FOX",
            "CFBundleShortVersionString": os.environ.get("FOX_VERSION", "0.0.0"),
            "CFBundleVersion": os.environ.get("FOX_VERSION", "0.0.0"),
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            # Senza queste due stringhe macOS termina l'app invece di chiedere il permesso
            "NSMicrophoneUsageDescription":
                "FOX usa il microfono per ricevere i tuoi comandi vocali.",
            "NSSpeechRecognitionUsageDescription":
                "FOX trascrive la tua voce localmente per eseguire i comandi.",
        },
    )
