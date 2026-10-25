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


BINARY_SUFFIXES = (".pyd", ".so", ".dll", ".dylib")


def try_collect(label, fn, *args, **kwargs):
    """Raccoglie senza far fallire il build se il pacchetto non c'è."""
    try:
        out = fn(*args, **kwargs)
        print("[fox.spec] %s: %d elementi" % (label, len(out)))
        return out
    except Exception as exc:                      # pacchetto assente o non installabile
        print("[fox.spec] %s non raccolto: %s" % (label, exc))
        return []


def data_files(pkg):
    """collect_data_files senza le estensioni binarie.

    collect_data_files considera "dati" anche i .pyd e i .so del pacchetto.
    Finiscono così nel bundle una seconda volta, accanto alla copia raccolta
    correttamente fra i binaries, e Python fallisce l'import con
    "cannot load module more than once per process". Il filtro evita il
    doppione, che è la causa classica di quell'errore.
    """
    collected = try_collect("%s (dati)" % pkg, collect_data_files, pkg)
    kept = [item for item in collected
            if not str(item[0]).lower().endswith(BINARY_SUFFIXES)]
    dropped = len(collected) - len(kept)
    if dropped:
        print("[fox.spec] %s: scartati %d file binari dai dati" % (pkg, dropped))
    return kept


# --- AI locale -------------------------------------------------------------
# Solo collect_dynamic_libs, MAI collect_data_files: quest'ultimo raccoglie gli
# stessi .dll/.dylib anche come dati, e la doppia copia fa fallire l'import con
# "cannot load module more than once per process".
binaries += try_collect("llama_cpp (binari)", collect_dynamic_libs, "llama_cpp")
hiddenimports += ["llama_cpp", "diskcache"]

# --- Riconoscimento vocale -------------------------------------------------
# faster-whisper usa ctranslate2, che è un'estensione C con librerie native.
binaries += try_collect("ctranslate2 (binari)", collect_dynamic_libs, "ctranslate2")
binaries += try_collect("tokenizers (binari)", collect_dynamic_libs, "tokenizers")
hiddenimports += ["ctranslate2", "tokenizers"]
for pkg in ("faster_whisper", "huggingface_hub"):
    datas += data_files(pkg)
    hiddenimports += try_collect("%s (moduli)" % pkg, collect_submodules, pkg)

# --- Audio: portaudio è una DLL/dylib separata, in un pacchetto a parte -----
binaries += try_collect("sounddevice", collect_dynamic_libs, "sounddevice")
binaries += try_collect("_sounddevice_data", collect_dynamic_libs, "_sounddevice_data")
datas += data_files("sounddevice")
datas += data_files("_sounddevice_data")
hiddenimports += ["_sounddevice_data"]

# --- numpy ------------------------------------------------------------------
# L'hook di PyInstaller resta indietro rispetto alle versioni nuove di numpy e
# lascia fuori sottomoduli come numpy._core._exceptions. Il risultato è
# "ImportError: cannot load module more than once per process", che è il
# messaggio con cui numpy riveste il vero errore ("No module named
# numpy._core._exceptions"). Raccoglierli esplicitamente lo evita, e siccome
# llama.cpp e faster-whisper importano numpy, rimette in piedi anche quelli.
hiddenimports += try_collect(
    "numpy (moduli)", collect_submodules, "numpy",
    filter=lambda name: ".tests" not in name and "f2py" not in name,
)
binaries += try_collect("numpy (binari)", collect_dynamic_libs, "numpy")

# --- Keychain: i backend si importano dinamicamente, PyInstaller non li vede ---
hiddenimports += try_collect("keyring", collect_submodules, "keyring.backends")

# --- Provider online ---
hiddenimports += ["anthropic", "openai", "httpx", "certifi"]

# --- Scorciatoia globale ---
hiddenimports += try_collect("pynput", collect_submodules, "pynput")

# --- Moduli di FOX ---
hiddenimports += [
    "island", "providers", "local_llm", "voice", "settings", "settings_ui",
    "diagnostics",
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
