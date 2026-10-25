"""F.O.X. — assistente personale desktop.

Punto di ingresso dell'applicazione. Tiene insieme l'isola (la superficie
permanente), la finestra di chat, la voce e i provider.

    python app.py
"""

from __future__ import annotations

import sys
import traceback

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTextBrowser, QVBoxLayout, QWidget,
)

import voice
from island import ACCENT, Island, State, ui_font
from providers import router
from settings import settings
from settings_ui import SettingsDialog

APP_TITLE = "FOX"


# ------------------------------------------------------------------ worker --

class GenerateWorker(QThread):
    """Genera la risposta in un thread, pezzo per pezzo."""

    chunk = Signal(str)
    done = Signal(str, str)      # testo completo, nome del provider usato
    failed = Signal(str)

    def __init__(self, messages: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._messages = messages
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        pieces: list[str] = []
        try:
            for piece in router.stream(self._messages):
                if self._stop:
                    break
                pieces.append(piece)
                self.chunk.emit(piece)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        provider = router.last_provider.label if router.last_provider else ""
        self.done.emit("".join(pieces), provider)


class VoiceWorker(QThread):
    """Registra dal microfono e trascrive."""

    level = Signal(float)
    transcribed = Signal(str)
    failed = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._recorder = voice.Recorder()

    def cancel(self) -> None:
        self._recorder.cancel()

    def run(self) -> None:
        try:
            audio = self._recorder.record(on_level=self.level.emit)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        if audio is None:
            self.transcribed.emit("")
            return
        try:
            self.transcribed.emit(voice.transcriber.transcribe(audio))
        except Exception as exc:
            self.failed.emit(str(exc))


class HotkeyBridge(QObject):
    """Porta la scorciatoia globale dal thread di pynput a quello di Qt."""

    pressed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._listener = None

    def start(self) -> str:
        combo = str(settings.get("hotkey", "ctrl+shift+space")).lower()
        try:
            from pynput import keyboard
        except Exception as exc:
            return "scorciatoia globale non attiva (%s)" % exc

        parts = [p.strip() for p in combo.split("+") if p.strip()]
        spec = "+".join("<%s>" % p for p in parts)
        try:
            self._listener = keyboard.GlobalHotKeys({spec: self.pressed.emit})
            self._listener.daemon = True
            self._listener.start()
        except Exception as exc:
            self._listener = None
            return "scorciatoia '%s' non registrata (%s)" % (combo, exc)
        return ""

    def stop(self) -> None:
        if self._listener is not None:
            try:
                self._listener.stop()
            except Exception:
                pass
            self._listener = None


# ------------------------------------------------------------- finestra ----

class ChatWindow(QWidget):
    """Finestra di conversazione. Si apre cliccando l'isola."""

    submitted = Signal(str)
    micRequested = Signal()
    settingsRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(560, 460)
        self._drag_from = None

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 14, 18, 18)

        self.frame = QWidget(self)
        shadow = QGraphicsDropShadowEffect(self.frame)
        shadow.setBlurRadius(44)
        shadow.setColor(QColor(0, 0, 0, 180))
        shadow.setOffset(0, 10)
        self.frame.setGraphicsEffect(shadow)
        self.frame.setStyleSheet(
            "background: #0A0A0C; border: 1px solid rgba(255,255,255,0.09);"
            "border-radius: 14px;"
        )
        root.addWidget(self.frame)

        inner = QVBoxLayout(self.frame)
        inner.setContentsMargins(16, 12, 16, 14)
        inner.setSpacing(10)

        inner.addLayout(self._build_titlebar())

        self.transcript = QTextBrowser()
        self.transcript.setOpenExternalLinks(True)
        self.transcript.setFont(ui_font(10))
        self.transcript.setStyleSheet(
            "QTextBrowser { background: transparent; border: none; color: #ECEDF0; }"
        )
        inner.addWidget(self.transcript, 1)

        inner.addLayout(self._build_input())
        self._append_system("Scrivi qui sotto, o tieni premuta la scorciatoia per parlare.")

    def _build_titlebar(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        title = QLabel(APP_TITLE)
        title.setFont(ui_font(10, QFont.DemiBold))
        title.setStyleSheet("color: rgba(255,138,43,0.95); background: transparent;")
        row.addWidget(title)

        self.provider_label = QLabel("")
        self.provider_label.setFont(ui_font(8))
        self.provider_label.setStyleSheet(
            "color: rgba(236,237,240,0.42); background: transparent;"
        )
        row.addWidget(self.provider_label)
        row.addStretch(1)

        for text, slot in (
            ("Impostazioni", self.settingsRequested.emit),
            ("Chiudi", self.hide),
        ):
            button = QPushButton(text)
            button.setFont(ui_font(9))
            button.setCursor(Qt.PointingHandCursor)
            button.setFlat(True)
            button.setStyleSheet(
                "QPushButton { color: rgba(236,237,240,0.55); border: none;"
                " background: transparent; padding: 2px 6px; }"
                "QPushButton:hover { color: #ECEDF0; }"
            )
            button.clicked.connect(slot)
            row.addWidget(button)
        return row

    def _build_input(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self.input = QLineEdit()
        self.input.setFont(ui_font(10))
        self.input.setPlaceholderText("Chiedi qualcosa…")
        self.input.setFixedHeight(38)
        self.input.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,0.055); color: #ECEDF0;"
            " border: 1px solid rgba(255,255,255,0.09); border-radius: 10px;"
            " padding: 0 12px; }"
            "QLineEdit:focus { border-color: rgba(255,138,43,0.55); }"
        )
        self.input.returnPressed.connect(self._submit)
        row.addWidget(self.input, 1)

        mic = QPushButton("Voce")
        mic.setFont(ui_font(9, QFont.DemiBold))
        mic.setCursor(Qt.PointingHandCursor)
        mic.setFixedHeight(38)
        mic.setStyleSheet(
            "QPushButton { background: rgba(255,138,43,0.92); color: #120A03;"
            " border: none; border-radius: 10px; padding: 0 16px; }"
            "QPushButton:hover { background: rgba(255,154,70,1); }"
        )
        mic.clicked.connect(self.micRequested.emit)
        row.addWidget(mic)
        return row

    # -- trascrizione -------------------------------------------------------

    def _submit(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.submitted.emit(text)

    def _html(self, who: str, color: str, body: str) -> str:
        safe = (
            body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("\n", "<br>")
        )
        return (
            '<div style="margin:0 0 12px 0">'
            '<span style="color:%s;font-weight:600">%s</span><br>'
            '<span style="color:#ECEDF0">%s</span></div>' % (color, who, safe)
        )

    def _append_system(self, text: str) -> None:
        self.transcript.append(
            '<div style="color:rgba(236,237,240,0.4);margin-bottom:12px">%s</div>' % text
        )

    def append_user(self, text: str) -> None:
        self.transcript.append(self._html("Tu", "rgba(236,237,240,0.5)", text))
        self._scroll()

    def start_answer(self) -> None:
        self._answer = ""
        self.transcript.append(self._html("FOX", "rgba(255,138,43,0.95)", ""))
        self._answer_block = self.transcript.document().blockCount()
        self._scroll()

    def update_answer(self, full_text: str) -> None:
        """Riscrive l'ultimo blocco con il testo accumulato."""
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.select(cursor.SelectionType.BlockUnderCursor)
        cursor.removeSelectedText()
        self.transcript.append(
            self._html("FOX", "rgba(255,138,43,0.95)", full_text)
        )
        self._scroll()

    def show_error(self, text: str) -> None:
        self.transcript.append(
            '<div style="color:#FF7A7A;margin-bottom:12px">%s</div>'
            % text.replace("\n", "<br>")
        )
        self._scroll()

    def set_provider(self, label: str) -> None:
        self.provider_label.setText(("· " + label) if label else "")

    def _scroll(self) -> None:
        bar = self.transcript.verticalScrollBar()
        bar.setValue(bar.maximum())

    # -- trascinamento della finestra senza barra di sistema ----------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_from = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_from)

    def mouseReleaseEvent(self, _event) -> None:
        self._drag_from = None


# ------------------------------------------------------------ orchestratore --

class Fox(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.history: list[dict] = []
        self.generator: GenerateWorker | None = None
        self.voice_worker: VoiceWorker | None = None

        self.island = Island()
        self.window = ChatWindow()
        self.hotkey = HotkeyBridge(self)

        self.island.clicked.connect(self.toggle_window)
        self.island.micRequested.connect(self.start_voice)
        self.island.stopRequested.connect(self.stop_generation)

        self.window.submitted.connect(self.ask)
        self.window.micRequested.connect(self.start_voice)
        self.window.settingsRequested.connect(self.open_settings)

        QShortcut(QKeySequence("Ctrl+,"), self.window, self.open_settings)
        QShortcut(QKeySequence("Esc"), self.window, self.window.hide)

        self.hotkey.pressed.connect(self.start_voice)
        problem = self.hotkey.start()
        if problem:
            print("[app] %s" % problem)

        self.island.show()
        self.position_window()

    # -- finestra -----------------------------------------------------------

    def position_window(self) -> None:
        screen = (self.island.screen() or QApplication.primaryScreen()).availableGeometry()
        self.window.move(
            screen.x() + (screen.width() - self.window.width()) // 2,
            screen.y() + 86,
        )

    def toggle_window(self) -> None:
        if self.window.isVisible():
            self.window.hide()
            return
        self.position_window()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        self.window.input.setFocus()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.window if self.window.isVisible() else None)
        dialog.exec()

    # -- voce ---------------------------------------------------------------

    def start_voice(self) -> None:
        if self.voice_worker is not None and self.voice_worker.isRunning():
            self.voice_worker.cancel()
            return
        if not settings.get("voice_input", True):
            self.island.set_state(State.ERROR, text="Voce disattivata nelle impostazioni",
                                  dismiss_ms=2600)
            return

        self.island.set_state(State.LISTENING)
        worker = VoiceWorker(self)
        worker.level.connect(self.island.set_audio_level)
        worker.transcribed.connect(self.on_transcribed)
        worker.failed.connect(self.on_voice_failed)
        worker.finished.connect(lambda: setattr(self, "voice_worker", None))
        self.voice_worker = worker
        worker.start()

    def on_transcribed(self, text: str) -> None:
        text = text.strip()
        if not text:
            self.island.set_state(State.IDLE)
            return
        self.ask(text)

    def on_voice_failed(self, message: str) -> None:
        self.island.set_state(State.ERROR, text=message, dismiss_ms=3200)
        self.window.show_error("Voce: " + message)

    # -- generazione --------------------------------------------------------

    def ask(self, text: str) -> None:
        if self.generator is not None and self.generator.isRunning():
            self.stop_generation()

        self.history.append({"role": "user", "content": text})
        self._trim_history()
        self.window.append_user(text)
        self.window.start_answer()
        self.island.set_state(State.THINKING)

        self._answer = ""
        worker = GenerateWorker(list(self.history), self)
        worker.chunk.connect(self.on_chunk)
        worker.done.connect(self.on_done)
        worker.failed.connect(self.on_failed)
        worker.finished.connect(lambda: setattr(self, "generator", None))
        self.generator = worker
        worker.start()

    def stop_generation(self) -> None:
        if self.generator is not None:
            self.generator.stop()
        voice.speaker.stop()
        self.island.set_state(State.IDLE)

    def on_chunk(self, piece: str) -> None:
        self._answer += piece
        if self.island.state is not State.ANSWER:
            self.island.set_state(State.ANSWER, text=self._answer)
        else:
            self.island.set_answer(self._answer)
        self.window.update_answer(self._answer)

    def on_done(self, full_text: str, provider: str) -> None:
        if full_text:
            self.history.append({"role": "assistant", "content": full_text})
            self._trim_history()
        self.window.set_provider(provider)
        self.island.set_state(State.IDLE)
        if settings.get("voice_output", True) and full_text:
            voice.speaker.say(full_text)

    def on_failed(self, message: str) -> None:
        first_line = message.splitlines()[0] if message else "errore"
        self.island.set_state(State.ERROR, text=first_line, dismiss_ms=4000)
        self.window.show_error(message)
        if not self.window.isVisible():
            self.toggle_window()

    def _trim_history(self) -> None:
        limit = int(settings.get("max_history", 20))
        if len(self.history) > limit:
            del self.history[: len(self.history) - limit]

    def shutdown(self) -> None:
        self.hotkey.stop()
        voice.speaker.stop()
        if self.generator is not None:
            self.generator.stop()
        if self.voice_worker is not None:
            self.voice_worker.cancel()


# -------------------------------------------------------------------- main --

def main() -> int:
    QApplication.setApplicationName(APP_TITLE)
    QApplication.setOrganizationName(APP_TITLE)
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)     # chiudere la chat non chiude FOX

    fox = Fox()
    app.aboutToQuit.connect(fox.shutdown)

    # Alla prima esecuzione non c'e' nulla di configurato: mostra le impostazioni.
    if not any(settings.api_key(p) for p in ("anthropic", "openai", "nvidia")) \
            and settings.local_model_path() is None:
        QTimer.singleShot(600, fox.open_settings)

    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(1)
