"""Render docs/screenshot.png: the real remote window, drawn offscreen at
2x with a soft drop shadow on a transparent background, so it reads well
on both GitHub's light and dark themes.

Also renders docs/social-preview.png, the 1280x640 card GitHub shows when
the repo link is shared (upload it in Settings > General > Social preview).

The device is a stand-in ("Living Room TV") so the image never shows your
own TV names. Pass the IP of a Roku on your network to fill the channel
row with its real app icons (read-only requests: the app list and icons):

    .venv/bin/python assets/gen_screenshot.py 192.168.1.50
"""

import json
import os
import sys
import tempfile
from pathlib import Path

# Must be set before Qt loads. Settings go to a throwaway directory so the
# render never reads or overwrites your saved devices.
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "2"
_scratch = tempfile.TemporaryDirectory()
os.environ["XDG_CONFIG_HOME"] = _scratch.name
os.environ["XDG_STATE_HOME"] = _scratch.name

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QRadialGradient  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QGraphicsDropShadowEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
)

from roku_remote import ecp, main, ui  # noqa: E402

OUT = ROOT / "docs" / "screenshot.png"
SOCIAL = ROOT / "docs" / "social-preview.png"
PAD = 96  # room for the shadow, in image pixels (2x)

roku_ip = sys.argv[1] if len(sys.argv) > 1 else None
ip = roku_ip or "192.0.2.10"  # TEST-NET address when no Roku is given

ecp.get_device = lambda _ip: {"name": "Living Room TV", "ip": ip, "serial": "DEMO"}
ecp.is_limited_mode = lambda _ip: False
if not roku_ip:
    ecp.get_apps = lambda _ip: []

app = QApplication(sys.argv)
app.setStyleSheet(ui.STYLE)
settings = QSettings("roku-remote", "roku-remote")
settings.setValue("devices", json.dumps([{"name": "Living Room TV", "ip": ip, "serial": "DEMO"}]))
settings.setValue("last_ip", ip)

window = main.RemoteWindow()
window.show()


def render():
    window.status.setText(main.KEY_HINTS)
    shot = window.grab()
    shot.setDevicePixelRatio(1)  # work in image pixels from here on

    # A real Gaussian drop shadow, shaped by the window's rounded corners.
    item = QGraphicsPixmapItem(shot)
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(64)
    shadow.setOffset(QPointF(0, 16))
    shadow.setColor(QColor(20, 0, 45, 110))
    item.setGraphicsEffect(shadow)
    scene = QGraphicsScene()
    scene.addItem(item)

    image = QImage(shot.width() + 2 * PAD, shot.height() + 2 * PAD, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    canvas = QRectF(image.rect())
    scene.render(painter, canvas, canvas.translated(-PAD, -PAD))  # window lands at (PAD, PAD)
    painter.end()
    OUT.parent.mkdir(exist_ok=True)
    image.save(str(OUT))
    print(f"Wrote {OUT} ({image.width()}x{image.height()})")
    render_social(image)
    app.quit()


def render_social(screenshot):
    """1280x640 card: name and pitch on the left, the remote on the right.
    Text stays inside a 64 px margin, which GitHub's crops never reach."""
    width, height, margin = 1280, 640, 64
    card = QImage(width, height, QImage.Format_ARGB32_Premultiplied)
    painter = QPainter(card)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)

    fill = QLinearGradient(0, 0, width, height)
    fill.setColorAt(0, QColor(ui.BG_TOP))
    fill.setColorAt(1, QColor(ui.BG_BOTTOM))
    painter.fillRect(card.rect(), fill)
    glow = QRadialGradient(QPointF(width * 0.78, height * 0.45), 520)
    glow.setColorAt(0, QColor(150, 80, 230, 90))
    glow.setColorAt(1, QColor(150, 80, 230, 0))
    painter.fillRect(card.rect(), glow)

    # The remote, scaled so its window (not its shadow) spans most of the height.
    scale = (height - 2 * 36) / (screenshot.height() - 2 * PAD)
    remote = screenshot.scaledToHeight(round(screenshot.height() * scale), Qt.SmoothTransformation)
    painter.drawImage(round(width - margin - remote.width() + PAD * scale), round((height - remote.height()) / 2), remote)

    icon = QImage(str(ROOT / "assets" / "roku-remote.png")).scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter.drawImage(margin, 132, icon)

    def text(y, size, weight, color, line):
        font = QFont(app.font())
        font.setPixelSize(size)
        font.setWeight(weight)
        painter.setFont(font)
        painter.setPen(QColor(color))
        painter.drawText(QRectF(margin, y, 720, size * 1.5), Qt.AlignLeft | Qt.AlignVCenter, line)

    text(250, 72, QFont.Bold, ui.TEXT, "Roku Remote")
    text(352, 32, QFont.Normal, ui.TEXT, "Control your Roku TV from your")
    text(396, 32, QFont.Normal, ui.TEXT, "Linux or Windows PC")
    text(470, 22, QFont.Normal, ui.MUTED, "Free and open source  |  No account  |  Keyboard control")
    text(512, 22, QFont.Normal, ui.MUTED, "github.com/averagenative/roku-remote")
    painter.end()
    card.save(str(SOCIAL))
    print(f"Wrote {SOCIAL} ({width}x{height})")


# Give the app list and icons time to load from the Roku.
QTimer.singleShot(4000 if roku_ip else 500, render)
app.exec()
