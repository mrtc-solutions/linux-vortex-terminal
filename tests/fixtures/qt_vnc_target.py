"""Real graphical application used as the acceptance target for remote desktops.

It is an ordinary Qt application (widgets, layout, event handlers) served over
the *real* RFB protocol by Qt's VNC platform plugin, which ships with the Qt
libraries that PyQt5 wheels bundle. Nothing here fakes a framebuffer: every
pixel the test inspects was rendered by Qt and encoded by Qt's VNC server.

The application writes its own state to a JSON file so acceptance runs can prove
that keyboard and pointer events delivered over RFB actually changed
target-side application state.

Environment:
  VRS_STATE  path of the JSON state file (default <tmp>/vortex-vnc-state.json)
  QT_QPA_PLATFORM  must be vnc:port=<port>[:size=WxH] (see docs/REMOTE_DESKTOP.md)
"""
from __future__ import annotations

import json
import os
import sys

from PyQt5.QtCore import QPoint, QTimer
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

STATE_PATH = os.environ.get("VRS_STATE", os.path.join(os.environ.get("TMPDIR", "/tmp"), "vortex-vnc-state.json"))


class AcceptanceWindow(QWidget):
    """A window whose widgets report their real geometry and live state."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Vortex VNC acceptance target")
        self.clicks = 0
        self.resize(560, 420)
        self.setAutoFillBackground(True)
        self.setStyleSheet("QWidget { background-color: rgb(20, 26, 24); color: rgb(220, 240, 230); }"
                           "QLineEdit { background-color: rgb(245, 245, 240); color: rgb(10, 10, 10); }"
                           "QPushButton { background-color: rgb(0, 200, 120); color: rgb(0, 0, 0); font-weight: bold; }")
        layout = QVBoxLayout(self)
        self.title = QLabel("VORTEX ACCEPTANCE TARGET")
        self.status = QLabel("ready")
        self.edit = QLineEdit()
        self.edit.setObjectName("vrs-input")
        self.edit.textChanged.connect(self.dump)
        self.button = QPushButton("PRESS ME")
        self.button.setObjectName("vrs-button")
        self.button.clicked.connect(self.on_click)
        layout.addWidget(self.title)
        layout.addWidget(self.status)
        layout.addWidget(self.edit)
        layout.addWidget(self.button)
        self.dump()
        # Report geometry once the window is mapped by the platform plugin.
        QTimer.singleShot(300, self.dump)

    def on_click(self) -> None:
        self.clicks += 1
        self.button.setText(f"PRESSED {self.clicks}")
        self.status.setText(f"button pressed {self.clicks} time(s)")
        self.dump()

    def widget_rect(self, widget: QWidget) -> dict:
        top_left = widget.mapToGlobal(QPoint(0, 0))
        return {
            "x": int(top_left.x()), "y": int(top_left.y()),
            "width": int(widget.width()), "height": int(widget.height()),
        }

    def dump(self) -> None:
        screen = self.screen()
        payload = {
            "text": self.edit.text(),
            "clicks": self.clicks,
            "status": self.status.text(),
            "button_label": self.button.text(),
            "window": {"width": int(self.width()), "height": int(self.height())},
            "button": self.widget_rect(self.button),
            "input": self.widget_rect(self.edit),
            "screen": {
                "width": int(screen.geometry().width()),
                "height": int(screen.geometry().height()),
                "depth": int(screen.depth()),
            },
            "pid": os.getpid(),
        }
        tmp = f"{STATE_PATH}.tmp"
        with open(tmp, "w") as handle:
            json.dump(payload, handle)
        os.replace(tmp, STATE_PATH)


def main() -> int:
    app = QApplication(sys.argv)
    window = AcceptanceWindow()
    window.show()
    # Prove the window is really painted by Qt, not a blank surface.
    window.setStyleSheet(window.styleSheet())
    app.processEvents()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
