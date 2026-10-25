"""L'isola: la superficie permanente di FOX.

Una pillola ancorata in alto al centro dello schermo che si espande in base
allo stato. Il reattore e' disegnato direttamente dalla card a posizione fissa,
cosi' resta fermo mentre il contenuto attorno cambia: e' l'ancora visiva
dell'intera interfaccia.
"""

from __future__ import annotations

import math
import sys
from enum import Enum, auto

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer, Signal,
)
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton,
    QStackedLayout, QWidget,
)

# ---------------------------------------------------------------- palette ---

BG = QColor(10, 10, 12, 242)
BORDER = QColor(255, 255, 255, 20)
TEXT = QColor(236, 237, 240)
TEXT_DIM = QColor(236, 237, 240, 150)
ACCENT = QColor(255, 138, 43)          # ambra FOX
DANGER = QColor(255, 86, 86)
OK = QColor(70, 214, 136)

MARGIN = 24        # spazio attorno alla card per l'ombra
TOP_INSET = 8      # distanza dal bordo alto dello schermo
REACTOR_X = 20     # centro del reattore dentro la card


def ui_font(size: int, weight: QFont.Weight = QFont.Medium) -> QFont:
    family = "SF Pro Text" if sys.platform == "darwin" else "Segoe UI"
    font = QFont(family, size)
    font.setWeight(weight)
    return font


class State(Enum):
    IDLE = auto()        # in attesa
    LISTENING = auto()   # microfono aperto
    THINKING = auto()    # il modello sta generando
    ANSWER = auto()      # risposta in arrivo, con anteprima
    ERROR = auto()       # qualcosa non ha funzionato


SIZES = {
    State.IDLE: (176, 38),
    State.LISTENING: (280, 46),
    State.THINKING: (300, 46),
    State.ANSWER: (460, 52),
    State.ERROR: (420, 48),
}

STATE_COLOR = {
    State.IDLE: ACCENT,
    State.LISTENING: ACCENT,
    State.THINKING: ACCENT,
    State.ANSWER: ACCENT,
    State.ERROR: DANGER,
}


# ------------------------------------------------------------- componenti ---

class Waveform(QWidget):
    """Barre che reagiscono al livello del microfono."""

    def __init__(self, bars: int = 15, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(bars * 5, 22)
        self._count = bars
        self._level = 0.2
        self._phase = 0.0
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(33)
        self._timer = timer

    def set_level(self, level: float) -> None:
        self._level = max(0.06, min(1.0, float(level)))

    def _tick(self) -> None:
        self._phase += 0.22
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(ACCENT)
        height = self.height()
        for i in range(self._count):
            envelope = math.sin(math.pi * (i + 0.5) / self._count)
            osc = 0.5 + 0.5 * math.sin(self._phase + i * 0.7)
            bar = max(3.0, height * self._level * envelope * (0.45 + 0.55 * osc))
            painter.drawRoundedRect(i * 5, (height - bar) / 2, 3, bar, 1.5, 1.5)


def pill_button(text: str, kind: str = "ghost") -> QPushButton:
    button = QPushButton(text)
    button.setFont(ui_font(9, QFont.DemiBold))
    button.setCursor(Qt.PointingHandCursor)
    button.setFixedHeight(26)
    palette = {
        "ghost": ("rgba(255,255,255,0.08)", "#ECEDF0", "rgba(255,255,255,0.15)"),
        "danger": ("rgba(255,86,86,0.16)", "#FF7A7A", "rgba(255,86,86,0.28)"),
    }[kind]
    button.setStyleSheet(
        "QPushButton { background: %s; color: %s; border: none;"
        " border-radius: 13px; padding: 0 12px; }"
        "QPushButton:hover { background: %s; }" % palette
    )
    return button


class Card(QWidget):
    """Il corpo scuro dell'isola. Disegna sfondo, bordo e reattore."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._radius = 19.0
        self._state = State.IDLE
        self._phase = 0.0
        timer = QTimer(self)
        timer.timeout.connect(self._tick)
        timer.start(16)
        self._timer = timer

    def set_radius(self, radius: float) -> None:
        self._radius = radius
        self.update()

    def set_state(self, state: State) -> None:
        self._state = state
        self.update()

    def _tick(self) -> None:
        self._phase += 0.045
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, self._radius, self._radius)
        painter.fillPath(path, BG)
        painter.setPen(QPen(BORDER, 1))
        painter.drawPath(path)

        self._paint_reactor(painter)

    def _paint_reactor(self, painter: QPainter) -> None:
        cx, cy = REACTOR_X, self.height() / 2
        radius = 7.0
        color = STATE_COLOR[self._state]

        if self._state in (State.THINKING, State.ANSWER):
            faint = QColor(color)
            faint.setAlpha(55)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(faint, 2))
            painter.drawEllipse(int(cx - radius), int(cy - radius),
                                int(radius * 2), int(radius * 2))
            pen = QPen(color, 2)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            start = int(math.degrees(self._phase * 2.2) * 16) % (360 * 16)
            painter.drawArc(
                QRect(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2)),
                start, 100 * 16,
            )
            return

        pulse = 0.5 + 0.5 * math.sin(self._phase * 1.6)
        glow = QColor(color)
        glow.setAlpha(int(38 + 52 * pulse))
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(int(cx - radius - 3), int(cy - radius - 3),
                            int((radius + 3) * 2), int((radius + 3) * 2))
        painter.setBrush(color)
        core = radius * (0.7 + 0.1 * pulse)
        painter.drawEllipse(int(cx - core), int(cy - core), int(core * 2), int(core * 2))


# ----------------------------------------------------------------- isola ----

class Island(QWidget):
    clicked = Signal()
    micRequested = Signal()
    stopRequested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)   # non ruba il fuoco
        self.setCursor(Qt.PointingHandCursor)

        self._state = State.IDLE

        self.card = Card(self)
        shadow = QGraphicsDropShadowEffect(self.card)
        shadow.setBlurRadius(38)
        shadow.setColor(QColor(0, 0, 0, 170))
        shadow.setOffset(0, 8)
        self.card.setGraphicsEffect(shadow)

        self.stack = QStackedLayout(self.card)
        self.stack.setContentsMargins(REACTOR_X + 18, 7, 14, 7)
        self._build_panels()

        self._anim = QPropertyAnimation(self, b"geometry", self)
        self._anim.setDuration(360)
        self._anim.setEasingCurve(QEasingCurve.OutBack)

        self._reset_timer = QTimer(self)
        self._reset_timer.setSingleShot(True)
        self._reset_timer.timeout.connect(lambda: self.set_state(State.IDLE))

        self.set_state(State.IDLE, animate=False)

    # -- costruzione --------------------------------------------------------

    def _label(self, text: str = "", size: int = 10,
               color: QColor = TEXT, weight: QFont.Weight = QFont.Medium) -> QLabel:
        label = QLabel(text)
        label.setFont(ui_font(size, weight))
        label.setStyleSheet(
            "color: rgba(%d,%d,%d,%.2f);"
            % (color.red(), color.green(), color.blue(), color.alpha() / 255)
        )
        return label

    def _panel(self, *widgets) -> QWidget:
        panel = QWidget()
        layout = QHBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        for widget in widgets:
            if widget is None:
                layout.addStretch(1)
            else:
                layout.addWidget(widget)
        return panel

    def _build_panels(self) -> None:
        self.idle_label = self._label("FOX", 10, TEXT_DIM, QFont.DemiBold)
        panel_idle = self._panel(self.idle_label, None)

        self.wave = Waveform()
        panel_listen = self._panel(self.wave, None, self._label("ascolto", 9, TEXT_DIM))

        self.think_label = self._label("elaboro", 10, TEXT_DIM)
        panel_think = self._panel(self.think_label, None)

        self.answer_label = self._label("", 10, TEXT)
        self.answer_label.setTextFormat(Qt.PlainText)
        self.btn_stop = pill_button("Stop", "ghost")
        self.btn_stop.clicked.connect(self.stopRequested.emit)
        panel_answer = self._panel(self.answer_label, None, self.btn_stop)

        self.error_label = self._label("", 10, DANGER)
        panel_error = self._panel(self.error_label, None)

        self._panels = {
            State.IDLE: panel_idle,
            State.LISTENING: panel_listen,
            State.THINKING: panel_think,
            State.ANSWER: panel_answer,
            State.ERROR: panel_error,
        }
        for panel in self._panels.values():
            self.stack.addWidget(panel)

    # -- stato --------------------------------------------------------------

    @property
    def state(self) -> State:
        return self._state

    def set_state(self, state: State, *, text: str = "",
                  animate: bool = True, dismiss_ms: int = 0) -> None:
        self._state = state
        self.card.set_state(state)
        self.stack.setCurrentWidget(self._panels[state])

        if state is State.THINKING:
            self.think_label.setText(text or "elaboro")
        elif state is State.ANSWER:
            self.set_answer(text)
        elif state is State.ERROR:
            self.error_label.setText(self._elide(text or "errore", 52))

        self._reset_timer.stop()
        if dismiss_ms:
            self._reset_timer.start(dismiss_ms)

        self._resize_to(state, animate)

    def set_answer(self, text: str) -> None:
        """Mostra la coda della risposta mentre arriva, su una riga sola."""
        flat = " ".join((text or "").split())
        self.answer_label.setText(self._elide(flat, 58, from_end=True))

    def set_audio_level(self, level: float) -> None:
        self.wave.set_level(level)

    @staticmethod
    def _elide(text: str, limit: int, from_end: bool = False) -> str:
        if len(text) <= limit:
            return text
        return ("…" + text[-limit:]) if from_end else (text[:limit] + "…")

    # -- geometria ----------------------------------------------------------

    def _target_geometry(self, state: State) -> QRect:
        width, height = SIZES[state]
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        total_w, total_h = width + MARGIN * 2, height + MARGIN * 2
        x = screen.x() + (screen.width() - total_w) // 2
        y = screen.y() + TOP_INSET - MARGIN
        return QRect(x, max(screen.y(), y), total_w, total_h)

    def _resize_to(self, state: State, animate: bool) -> None:
        target = self._target_geometry(state)
        width, height = SIZES[state]
        self.card.setGeometry(MARGIN, MARGIN, width, height)
        self.card.set_radius(min(height / 2, 24))
        if animate and self.isVisible():
            self._anim.stop()
            self._anim.setStartValue(self.geometry())
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self.setGeometry(target)

    def resizeEvent(self, event) -> None:
        self.card.setGeometry(
            MARGIN, MARGIN, self.width() - MARGIN * 2, self.height() - MARGIN * 2
        )
        super().resizeEvent(event)

    # -- interazione --------------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        elif event.button() == Qt.RightButton:
            self.micRequested.emit()
        super().mousePressEvent(event)


if __name__ == "__main__":
    # Anteprima: cicla gli stati senza il resto dell'app.
    app = QApplication(sys.argv)
    island = Island()
    island.show()
    script = [
        (1200, lambda: island.set_state(State.LISTENING)),
        (3000, lambda: island.set_state(State.THINKING)),
        (4600, lambda: island.set_state(State.ANSWER, text="Ho trovato tre riunioni domani")),
        (7000, lambda: island.set_state(State.ERROR, text="Nessun provider disponibile",
                                        dismiss_ms=2500)),
    ]
    for delay, action in script:
        QTimer.singleShot(delay, action)
    sys.exit(app.exec())
