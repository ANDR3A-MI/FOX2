"""Finestra delle impostazioni: provider, chiavi, modelli locali, voce."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QProgressBar,
    QPushButton, QTabWidget, QVBoxLayout, QWidget,
)

import local_llm
import voice
from settings import PROVIDER_LABELS, settings

STYLE = """
QDialog, QWidget { background: #0A0A0C; color: #ECEDF0; }
QLabel { color: #ECEDF0; }
QLabel[hint="true"] { color: rgba(236,237,240,0.45); }
QLineEdit, QComboBox, QListWidget {
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
QTabWidget::pane { border: 1px solid rgba(255,255,255,0.09); border-radius: 10px; }
QTabBar::tab {
    background: transparent; color: rgba(236,237,240,0.55);
    padding: 7px 14px; border: none;
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


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Impostazioni FOX")
        self.setStyleSheet(STYLE)
        self.resize(560, 520)
        self.downloader: DownloadWorker | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        tabs = QTabWidget()
        tabs.addTab(self._tab_providers(), "Provider")
        tabs.addTab(self._tab_local(), "AI locale")
        tabs.addTab(self._tab_voice(), "Voce")
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

    # -- provider -----------------------------------------------------------

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
        self.order_list.setFixedHeight(130)
        for key in settings.get("provider_order"):
            if key in PROVIDER_LABELS:
                item = QListWidgetItem(PROVIDER_LABELS[key])
                item.setData(Qt.UserRole, key)
                self.order_list.addItem(item)
        layout.addWidget(self.order_list)

        form = QFormLayout()
        form.setSpacing(9)
        self.key_fields: dict[str, QLineEdit] = {}
        for key, placeholder in (
            ("anthropic", "sk-ant-…"),
            ("openai", "sk-…"),
            ("nvidia", "nvapi-…"),
        ):
            field = QLineEdit()
            field.setEchoMode(QLineEdit.Password)
            field.setPlaceholderText(placeholder)
            if settings.api_key(key):
                field.setText(settings.api_key(key))
            self.key_fields[key] = field
            form.addRow(PROVIDER_LABELS[key], field)

        self.model_fields: dict[str, QLineEdit] = {}
        for key, setting_key in (
            ("anthropic", "model_anthropic"),
            ("openai", "model_openai"),
            ("nvidia", "model_nvidia"),
        ):
            field = QLineEdit(str(settings.get(setting_key)))
            self.model_fields[setting_key] = field
            form.addRow("Modello %s" % PROVIDER_LABELS[key], field)
        layout.addLayout(form)

        if not settings.keyring_available:
            layout.addWidget(self._hint(
                "Il keychain di sistema non e' disponibile: le chiavi restano "
                "solo in memoria e vanno reinserite al prossimo avvio."
            ))
        else:
            layout.addWidget(self._hint(
                "Le chiavi sono salvate nel keychain di sistema, mai in chiaro. "
                "Le chiavi NVIDIA NIM si ottengono su build.nvidia.com."
            ))
        layout.addStretch(1)
        return page

    # -- AI locale ----------------------------------------------------------

    def _tab_local(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        if not local_llm.available():
            layout.addWidget(self._hint(local_llm.unavailable_reason()))

        layout.addWidget(QLabel("Modello attivo"))
        self.model_combo = QComboBox()
        self._refresh_models()
        layout.addWidget(self.model_combo)

        layout.addWidget(self._hint(
            "Il modello gira dentro FOX: niente Ollama, niente LM Studio, "
            "nessuna chiave. Funziona anche senza connessione."
        ))

        layout.addWidget(QLabel("Scarica un modello"))
        self.catalog_combo = QComboBox()
        for info in local_llm.CATALOG:
            suffix = " — gia' installato" if info.installed else " — %d MB" % info.size_mb
            self.catalog_combo.addItem(info.label + suffix, info.key)
        self.catalog_combo.currentIndexChanged.connect(self._update_note)
        layout.addWidget(self.catalog_combo)

        self.catalog_note = self._hint("")
        layout.addWidget(self.catalog_note)
        self._update_note()

        row = QHBoxLayout()
        self.download_button = QPushButton("Scarica")
        self.download_button.setProperty("accent", True)
        self.download_button.clicked.connect(self._start_download)
        row.addWidget(self.download_button)
        row.addStretch(1)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.progress_label = self._hint("")
        layout.addWidget(self.progress_label)
        layout.addStretch(1)
        return page

    def _refresh_models(self) -> None:
        self.model_combo.clear()
        current = settings.get("local_model_file")
        found = local_llm.installed_models()
        if not found:
            self.model_combo.addItem("Nessun modello installato", "")
            return
        for path in found:
            self.model_combo.addItem(path.name, path.name)
        if current:
            index = self.model_combo.findData(current)
            if index >= 0:
                self.model_combo.setCurrentIndex(index)

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

    # -- voce ---------------------------------------------------------------

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

        problem = voice.microphone_problem()
        if problem:
            layout.addWidget(self._hint("Microfono non disponibile: " + problem))

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
            "Il riconoscimento vocale funziona offline. Un modello Whisper piu' "
            "grande e' piu' preciso ma piu' lento. La scorciatoia si applica al "
            "prossimo avvio."
        ))
        layout.addStretch(1)
        return page

    # -- comune -------------------------------------------------------------

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
            model_anthropic=self.model_fields["model_anthropic"].text().strip(),
            model_openai=self.model_fields["model_openai"].text().strip(),
            model_nvidia=self.model_fields["model_nvidia"].text().strip(),
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
