"""Render the app icon: Roku wordmark (Roku_logo.svg, recolored white)
centered on a purple rounded-square tile, like the official phone app."""

import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parent.parent

app = QApplication(sys.argv)
size = 256
image = QImage(size, size, QImage.Format_ARGB32)
image.fill(Qt.transparent)

painter = QPainter(image)
painter.setRenderHint(QPainter.Antialiasing)

painter.setBrush(QBrush(QColor("#662d91")))
painter.setPen(Qt.NoPen)
painter.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)

svg = (ROOT / "Roku_logo.svg").read_text().replace("#6c3c97", "#ffffff")
renderer = QSvgRenderer(QByteArray(svg.encode()))
logo_size = renderer.defaultSize()

pad = 36
avail = size - 2 * pad
scale = min(avail / logo_size.width(), avail / logo_size.height())
w = logo_size.width() * scale
h = logo_size.height() * scale
renderer.render(painter, QRectF((size - w) / 2, (size - h) / 2, w, h))

painter.end()
image.save(str(ROOT / "assets" / "roku-remote.png"))
print("wrote assets/roku-remote.png")
