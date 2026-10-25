"""Finestra delle impostazioni: provider, modelli locali, voce, diagnostica."""

from __future__ import annotations

import platform
import shutil
import sys
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

import local_llm
import providers
import voice
from settings import PROVIDER_LABELS, config_dir, models_dir, settings

STYLE = """
QDialog, QWidget { background: #0A0A0C; color: #ECEDF0; }
QLabel { color: #ECEDF0; }
QLabel[hint="true"] { color: rgba(236,237,240,0.45); }
QLineEdit, QComboBox, QListWidget, QTextBrowser {
    background: rgba(255,255,255,0.055);
    border: 1px solid rgba(255,255,255,0.10);
    border-radius: 8px; padding: 6px 9px; color: #ECEDF0;
}
QLineEdit:focus, QComboBox:focus { border-color: rgba(255,138,43,0.55); }
QPushButton {
    background: rgba(255,255,255,0.08); border: none; border-radius: 8px;
    padding: 7px 14px; color: #ECEDF0;
}
QPushButton:hover { background: rgba(255,255,255,0.14); }
QPushButton[accent="true"] { background: rgba(255,138,43,0.92); color: #120A03; }
QPushButton[accent="true"]:hover { background: rgba(255,154,70,1); }
QPushButton[danger="true"] { background: rgba(255,86,86,0.16); color: #FF7A7A; }
QPushButton[compact="true"] { padding: 6px 10px; }
QTabWidget::pane { border: 1px solid rgba(255,255,255,0.09); border-radius: 10px; }
QTabBar::tab {
    background: transparent; color: rgba(236,237,240,0.55);
    padding: 7px 13px; border: none;
}
QTabBar::tab:selected { color: #FF8A2B; }
QProgressBar {
    background: rgba(255,255,255,0.06); border: none; border-radius: 4px;
    height: 7px; text-align: center; color: transparent;
}
QProgressBar::chunk { background: #FF8A2B; border-radius: 4px; }
QCheckBox { color: #ECEDF0; }
"""


class DownloadWorker(QThread):
    progress = Signal(int, int)
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, info: local_llm.ModelInfo, parent=None) -> None:
        super().__init__(parent)
        self.info = info
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            path = local_llm.download_model(
                self.info, on_progress=self.progress.emit, cancel=self._cancel
            )
        except local_llm.DownloadCancelled:
            self.failed.emit("Download annullato.")
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.done.emit(path.name)


class ModelListWorker(QThread):
    """Chiede al provider quali modelli accetta la chiave adesso."""

    done = Signal(str, list)
    failed = Signal(str, str)

    def __init__(self, provider_id: str, parent=None) -> None:
        super().__init__(parent)
        self.provider_id = provider_id

    def run(self) -> None:
        provider = providers.ALL[self.provider_id]
        try:
            names = provider.list_models()
        except Exception as exc:
            self.failed.emit(self.provider_id, str(exc))
        else:
            self.done.emit(self.provider_id, names)


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Impostazioni FOX")
        self.setStyleSheet(STYLE)
        self.resize(620, 580)
        self.downloader: DownloadWorker | None = None
        self.model_workers: dict[str, ModelListWorker] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        tabs = QTabWidget()
        tabs.addTab(self._tab_providers(), "Provider")
        tabs.addTab(self._tab_local(), "AI locale")
        tabs.addTab(self._tab_voice(), "Voce")
        tabs.addTab(self._tab_diagnostics(), "Diagnostica")
        root.addWidget(tabs, 1)

        row = QHBoxLayout()
        quit_button = QPushButton("Esci da FOX")
        quit_button.setProperty("danger", True)
        quit_button.clicked.connect(self._quit_app)
        row.addWidget(quit_button)
        row.addStretch(1)

        close_button = QPushButton("Chiudi")
        close_button.clicked.connect(self.reject)
        row.addWidget(close_button)

        save_button = QPushButton("Salva")
        save_button.setProperty("accent", True)
        save_button.clicked.connect(self._save)
        row.addWidget(save_button)
        root.addLayout(row)

    # ------------------------------------------------------------ provider --

    def _tab_providers(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(self._hint(
            "FOX prova i provider dall'alto verso il basso e scende al successivo "
            "se uno non risponde. Trascina per riordinare."
        ))

        self.order_list = QListWidget()
        self.order_list.setDragDropMode(QListWidget.InternalMove)
        self.order_list.setFixedHeight(120)
        for key in settings.get("provider_order"):
            if key in PROVIDER_LABELS:
                item = QListWidgetItem(PROVIDER_LABELS[key])
                item.setData(Qt.UserRole, key)
                self.order_list.addItem(item)
        layout.addWidget(self.order_list)

        form = QFormLayout()
        form.setSpacing(9)
        self.key_fields: dict[str, QLineEdit] = {}
        self.model_combos: dict[str, QComboBox] = {}
        self.model_buttons: dict[str, QPushButton] = {}

        for key, placeholder, setting_key in (
            ("anthropic", "sk-ant-…", "model_anthropic"),
            ("openai", "sk-…", "model_openai"),
            ("nvidia", "nvapi-…", "model_nvidia"),
        ):
            field = QLineEdit()
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(placeholder)
            if settings.api_key(key):
                field.setText(settings.api_key(key))
            self.key_fields[key] = field
            form.addRow("Chiave %s" % PROVIDER_LABELS[key], field)

            combo = QComboBox()
            combo.setEditable(True)
            combo.addItem(str(settings.get(setting_key)))
            combo.setCurrentText(str(settings.get(setting_key)))
            self.model_combos[setting_key] = combo

            button = QPushButton("Carica modelli")
            button.setProperty("compact", True)
            button.clicked.connect(lambda _=False, k=key: self._load_models(k))
            self.model_buttons[key] = button

            row = QHBoxLayout()
            row.setSpacing(8)
            row.addWidget(combo, 1)
            row.addWidget(button)
            holder = QWidget()
            holder.setLayout(row)
            form.addRow("Modello %s" % PROVIDER_LABELS[key], holder)

        layout.addLayout(form)

        self.models_note = self._hint(
            "I cataloghi cambiano: un modello valido oggi puo' sparire fra sei "
            "mesi. 'Carica modelli' chiede al provider quali accetta la tua "
            "chiave adesso."
        )
        layout.addWidget(self.models_note)

        if not settings.keyring_available:
            layout.addWidget(self._hint(
                "Il keychain di sistema non e' disponibile: le chiavi restano "
                "solo in memoria e vanno reinserite al prossimo avvio."
            ))
        layout.addStretch(1)
        return page

    def _load_models(self, provider_id: str) -> None:
        if not settings.api_key(provider_id):
            field = self.key_fields[provider_id]
            if field.text().strip():
                settings.set_api_key(provider_id, field.text())
            else:
                self.models_note.setText(
                    "Incolla prima la chiave %s, poi premi di nuovo."
                    % PROVIDER_LABELS[provider_id]
                )
                return

        self.model_buttons[provider_id].setEnabled(False)
        self.models_note.setText("Chiedo l'elenco a %s…" % PROVIDER_LABELS[provider_id])

        worker = ModelListWorker(provider_id, self)
        worker.done.connect(self._on_models)
        worker.failed.connect(self._on_models_failed)
        worker.finished.connect(lambda k=provider_id: self.model_buttons[k].setEnabled(True))
        self.model_workers[provider_id] = worker
        worker.start()

    def _on_models(self, provider_id: str, names: list) -> None:
        setting_key = {"anthropic": "model_anthropic",
                       "openai": "model_openai",
                       "nvidia": "model_nvidia"}[provider_id]
        combo = self.model_combos[setting_key]
        current = combo.currentText()
        combo.clear()
        combo.addItems(names)
        if current in names:
            combo.setCurrentText(current)
        elif names:
            combo.setCurrentIndex(0)
        self.models_note.setText(
            "%d modelli disponibili su %s. Scegline uno e salva."
            % (len(names), PROVIDER_LABELS[provider_id])
        )

    def _on_models_failed(self, provider_id: str, message: str) -> None:
        self.models_note.setText(message)

    # ----------------------------------------------------------- AI locale --

    def _tab_local(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        if not local_llm.available():
            layout.addWidget(self._hint(local_llm.unavailable_reason()))

        layout.addWidget(QLabel("Modello attivo"))

        row = QHBoxLayout()
        row.setSpacing(8)
        self.model_combo = QComboBox()
        row.addWidget(self.model_combo, 1)

        add_button = QPushButton("Aggiungi dal PC…")
        add_button.setProperty("compact", True)
        add_button.clicked.connect(self._add_model_from_disk)
        row.addWidget(add_button)
        layout.addLayout(row)

        self._refresh_models()

        self.local_note = self._hint(
            "Il modello gira dentro FOX: niente Ollama, niente LM Studio, "
            "nessuna chiave. Se hai gia' un .gguf sul computer, aggiungilo da "
            "qui: FOX lo usa dove si trova, senza copiarlo."
        )
        layout.addWidget(self.local_note)

        layout.addWidget(QLabel("Oppure scaricane uno"))
        self.catalog_combo = QComboBox()
        for info in local_llm.CATALOG:
            suffix = " — gia' installato" if info.installed else " — %d MB" % info.size_mb
            self.catalog_combo.addItem(info.label + suffix, info.key)
        self.catalog_combo.currentIndexChanged.connect(self._update_note)
        layout.addWidget(self.catalog_combo)

        self.catalog_note = self._hint("")
        layout.addWidget(self.catalog_note)
        self._update_note()

        buttons = QHBoxLayout()
        self.download_button = QPushButton("Scarica")
        self.download_button.setProperty("accent", True)
        self.download_button.clicked.connect(self._start_download)
        buttons.addWidget(self.download_button)

        folder_button = QPushButton("Apri cartella modelli")
        folder_button.clicked.connect(self._open_models_folder)
        buttons.addWidget(folder_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.progress_label = self._hint("")
        layout.addWidget(self.progress_label)
        layout.addStretch(1)
        return page

    def _refresh_models(self) -> None:
        self.model_combo.clear()
        current = str(settings.get("local_model_file") or "")
        found = local_llm.installed_models()
        if not found:
            self.model_combo.addItem("Nessun modello installato", "")
            return
        for path in found:
            value = local_llm.model_setting_value(path)
            label = path.name if value == path.name else "%s  (%s)" % (path.name, path.parent)
            self.model_combo.addItem(label, value)
        index = self.model_combo.findData(current)
        if index >= 0:
            self.model_combo.setCurrentIndex(index)

    def _add_model_from_disk(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(
            self, "Scegli un modello GGUF", str(Path.home()),
            "Modelli GGUF (*.gguf);;Tutti i file (*)",
        )
        if not path_str:
            return

        path = Path(path_str)
        problem = local_llm.looks_like_gguf(path)
        if problem:
            QMessageBox.warning(self, "FOX", problem)
            return

        settings.update(local_model_file=local_llm.model_setting_value(path))
        self._refresh_models()
        size_gb = path.stat().st_size / (1024 ** 3)
        self.local_note.setText(
            "Modello attivo: %s (%.1f GB). FOX lo legge da dove si trova: se "
            "sposti o rinomini il file, torna qui a riselezionarlo."
            % (path.name, size_gb)
        )

    def _open_models_folder(self) -> None:
        folder = str(models_dir())
        try:
            if sys.platform == "win32":
                import os
                os.startfile(folder)                      # noqa: S606
            elif sys.platform == "darwin":
                import subprocess
                subprocess.Popen(["open", folder])
            else:
                import subprocess
                subprocess.Popen(["xdg-open", folder])
        except Exception as exc:
            QMessageBox.information(self, "FOX", "%s\n\n%s" % (folder, exc))

    def _selected_catalog(self) -> local_llm.ModelInfo:
        key = self.catalog_combo.currentData()
        for info in local_llm.CATALOG:
            if info.key == key:
                return info
        return local_llm.CATALOG[0]

    def _update_note(self) -> None:
        self.catalog_note.setText(self._selected_catalog().note)

    def _start_download(self) -> None:
        if self.downloader is not None and self.downloader.isRunning():
            self.downloader.cancel()
            return

        info = self._selected_catalog()
        if info.installed:
            QMessageBox.information(self, "FOX", "Questo modello e' gia' installato.")
            return

        self.progress.setVisible(True)
        self.progress.setValue(0)
        self.download_button.setText("Annulla")
        self.progress_label.setText("Scarico %s…" % info.label)

        worker = DownloadWorker(info, self)
        worker.progress.connect(self._on_progress)
        worker.done.connect(self._on_downloaded)
        worker.failed.connect(self._on_download_failed)
        worker.finished.connect(self._reset_download_ui)
        self.downloader = worker
        worker.start()

    def _on_progress(self, done: int, total: int) -> None:
        if total:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(done * 100 / total))
            self.progress_label.setText(
                "%d MB di %d MB" % (done // 1048576, total // 1048576)
            )
        else:
            self.progress.setRange(0, 0)
            self.progress_label.setText("%d MB" % (done // 1048576))

    def _on_downloaded(self, filename: str) -> None:
        settings.update(local_model_file=filename)
        self._refresh_models()
        self.progress_label.setText("Pronto: %s" % filename)

    def _on_download_failed(self, message: str) -> None:
        self.progress_label.setText(message)

    def _reset_download_ui(self) -> None:
        self.progress.setVisible(False)
        self.download_button.setText("Scarica")
        self.downloader = None

    # ---------------------------------------------------------------- voce --

    def _tab_voice(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        self.voice_in = QCheckBox("Comandi vocali")
        self.voice_in.setChecked(bool(settings.get("voice_input", True)))
        layout.addWidget(self.voice_in)

        self.voice_out = QCheckBox("Risposte a voce")
        self.voice_out.setChecked(bool(settings.get("voice_output", True)))
        layout.addWidget(self.voice_out)

        for problem in (voice.microphone_problem(), voice.whisper_problem()):
            if problem:
                layout.addWidget(self._hint("Non disponibile: " + problem))

        form = QFormLayout()
        form.setSpacing(9)

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny", "base", "small", "medium"])
        current = str(settings.get("whisper_model", "base"))
        if current in ("tiny", "base", "small", "medium"):
            self.whisper_combo.setCurrentText(current)
        form.addRow("Modello Whisper", self.whisper_combo)

        self.voice_combo = QComboBox()
        self.voice_combo.addItem("Voce predefinita del sistema", "")
        for name in voice.list_voices():
            self.voice_combo.addItem(name, name)
        saved = str(settings.get("tts_voice", ""))
        if saved:
            index = self.voice_combo.findData(saved)
            if index >= 0:
                self.voice_combo.setCurrentIndex(index)
        form.addRow("Voce", self.voice_combo)

        self.hotkey_field = QLineEdit(str(settings.get("hotkey")))
        form.addRow("Scorciatoia", self.hotkey_field)
        layout.addLayout(form)

        layout.addWidget(self._hint(
            "Il riconoscimento funziona offline, ma la prima volta scarica il "
            "modello Whisper da internet: la prima frase puo' richiedere un "
            "minuto. La scorciatoia si applica al prossimo avvio."
        ))
        layout.addStretch(1)
        return page

    # -------------------------------------------------------- diagnostica --

    def _tab_diagnostics(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        layout.addWidget(self._hint(
            "Stato di ogni componente. Se qualcosa non funziona, copia questo "
            "testo: contiene l'errore vero, non una versione addolcita."
        ))

        self.report = QTextBrowser()
        self.report.setFont(self.font())
        layout.addWidget(self.report, 1)

        row = QHBoxLayout()
        refresh = QPushButton("Aggiorna")
        refresh.clicked.connect(self._fill_report)
        row.addWidget(refresh)

        copy = QPushButton("Copia")
        copy.setProperty("accent", True)
        copy.clicked.connect(
            lambda: QGuiApplication.clipboard().setText(self.report.toPlainText())
        )
        row.addWidget(copy)
        row.addStretch(1)
        layout.addLayout(row)

        self._fill_report()
        return page

    def _fill_report(self) -> None:
        def mark(ok: bool) -> str:
            return "OK  " if ok else "NO  "

        lines: list[str] = []
        lines.append("FOX — diagnostica")
        lines.append("Sistema: %s %s (%s)" % (
            platform.system(), platform.release(), platform.machine()))
        lines.append("Python: %s" % sys.version.split()[0])
        lines.append("Eseguibile congelato: %s" % bool(getattr(sys, "frozen", False)))
        lines.append("Cartella impostazioni: %s" % config_dir())
        lines.append("")

        lines.append("AI LOCALE")
        ok_llama = local_llm.available()
        lines.append("%sllama.cpp" % mark(ok_llama))
        if not ok_llama:
            lines.append(local_llm.import_error().strip() or "causa sconosciuta")
        found = local_llm.installed_models()
        lines.append("%s%d modello/i trovato/i" % (mark(bool(found)), len(found)))
        for path in found:
            lines.append("      %s" % path)
        active = settings.local_model_path()
        lines.append("    attivo: %s" % (active or "nessuno"))
        lines.append("")

        lines.append("VOCE")
        mic = voice.microphone_problem()
        lines.append("%smicrofono%s" % (mark(not mic), "" if not mic else ": " + mic))
        for device in voice.input_devices():
            lines.append("      %s" % device)
        whisper = voice.whisper_problem()
        lines.append("%sfaster-whisper%s" % (
            mark(not whisper), "" if not whisper else ": " + whisper))
        lines.append("    modello Whisper: %s" % settings.get("whisper_model"))
        tts = voice.tts_problem()
        lines.append("%ssintesi vocale%s" % (mark(not tts), "" if not tts else ": " + tts))
        voices = voice.list_voices()
        lines.append("    %d voci di sistema" % len(voices))
        if voices:
            lines.append("      %s" % ", ".join(voices[:6]))
        lines.append("")

        lines.append("PROVIDER")
        for provider in providers.router.order():
            ready = provider.ready()
            lines.append("%s%s%s" % (
                mark(ready), provider.label,
                "" if ready else " — " + provider.why_not_ready()))
        lines.append("")

        lines.append("ALTRO")
        for module in ("PySide6", "numpy", "sounddevice", "keyring", "pynput",
                       "anthropic", "openai", "ctranslate2"):
            try:
                __import__(module)
            except Exception as exc:
                lines.append("%s%s: %s" % (mark(False), module, exc))
            else:
                lines.append("%s%s" % (mark(True), module))
        lines.append("%sffmpeg nel PATH" % mark(bool(shutil.which("ffmpeg"))))

        self.report.setPlainText("\n".join(lines))

    # -------------------------------------------------------------- comune --

    @staticmethod
    def _hint(text: str) -> QLabel:
        label = QLabel(text)
        label.setProperty("hint", True)
        label.setWordWrap(True)
        return label

    def _save(self) -> None:
        order = [
            self.order_list.item(i).data(Qt.UserRole)
            for i in range(self.order_list.count())
        ]
        in_memory_only = []
        for key, field in self.key_fields.items():
            if not settings.set_api_key(key, field.text()) and field.text().strip():
                in_memory_only.append(PROVIDER_LABELS[key])

        settings.update(
            provider_order=order,
            model_anthropic=self.model_combos["model_anthropic"].currentText().strip(),
            model_openai=self.model_combos["model_openai"].currentText().strip(),
            model_nvidia=self.model_combos["model_nvidia"].currentText().strip(),
            local_model_file=self.model_combo.currentData() or "",
            voice_input=self.voice_in.isChecked(),
            voice_output=self.voice_out.isChecked(),
            whisper_model=self.whisper_combo.currentText(),
            tts_voice=self.voice_combo.currentData() or "",
            hotkey=self.hotkey_field.text().strip() or "ctrl+shift+space",
        )

        if in_memory_only:
            QMessageBox.warning(
                self, "FOX",
                "Queste chiavi non sono state salvate nel keychain e andranno "
                "reinserite al prossimo avvio: " + ", ".join(in_memory_only),
            )
        self.accept()

    def _quit_app(self) -> None:
        answer = QMessageBox.question(
            self, "FOX", "Chiudere FOX?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            self.accept()
            QApplication.instance().quit()
