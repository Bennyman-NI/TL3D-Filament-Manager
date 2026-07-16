from __future__ import annotations

import sys
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("TL3D Filament Manager")
        self.resize(720, 480)

        title = QLabel("TL3D Filament Manager")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 26px; font-weight: 600;")

        status = QLabel("Spoolman integration setup pending")
        status.setAlignment(Qt.AlignmentFlag.AlignCenter)

        import_button = QPushButton("Import 3D Filament Profiles")
        import_button.setEnabled(False)

        schema_button = QPushButton("Spoolman API schema required")
        schema_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addStretch()
        layout.addWidget(title)
        layout.addWidget(status)
        layout.addSpacing(24)
        layout.addWidget(import_button)
        layout.addWidget(schema_button)
        layout.addStretch()

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)


def main() -> int:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
