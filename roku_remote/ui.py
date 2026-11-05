"""Look and feel: palette, stylesheet, drawn icons and custom widgets.

Icons are inline SVG rendered at runtime rather than font glyphs: the
user's system font lacks several symbol blocks (they render blank), and
drawn icons look the same on Linux and Windows.
"""

import math

from PySide6.QtCore import QByteArray, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QIcon,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QComboBox, QStyle, QStyleOptionComboBox, QStylePainter, QWidget

TEXT = "#f4effc"
MUTED = "#a497bb"
ACCENT = "#7d3cc4"
ACCENT_LIGHT = "#9658dc"
ACCENT_DARK = "#4f2382"
POWER_RED = "#ff6b6b"
BG_TOP = "#2b1846"
BG_BOTTOM = "#120a1c"

SURFACE = "rgba(255, 255, 255, 16)"
SURFACE_HOVER = "rgba(255, 255, 255, 30)"
OUTLINE = "rgba(190, 150, 255, 60)"

LINK_COLORS = {
    "ok": "#4ade80",     # connected
    "busy": "#fbbf24",   # connecting / searching
    "lost": "#f87171",   # not found
    "idle": "#6b5d80",   # not the selected device
}

STYLE = f"""
QDialog {{
    background-color: #1b1029;
}}
QLabel {{
    color: {TEXT};
    font-size: 13px;
}}
QLabel#title {{
    font-size: 14px;
    font-weight: 600;
}}
QLabel#statusLabel {{
    color: {MUTED};
    font-size: 11px;
}}
QToolTip {{
    background-color: #241536;
    color: {TEXT};
    border: 1px solid {OUTLINE};
    padding: 4px 8px;
}}
QComboBox#deviceBox {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {OUTLINE};
    border-radius: 19px;
    padding: 0 32px 0 14px;
    min-height: 36px;
    font-size: 13px;
}}
QComboBox#deviceBox:hover {{
    background-color: {SURFACE_HOVER};
}}
QComboBox#deviceBox::drop-down {{
    border: none;
    width: 32px;
}}
QComboBox#deviceBox::down-arrow {{
    image: none;
}}
QComboBox QAbstractItemView {{
    background-color: #221433;
    color: {TEXT};
    border: 1px solid {OUTLINE};
    padding: 4px;
    outline: none;
}}
QComboBox QAbstractItemView::item {{
    min-height: 30px;
    padding: 0 8px;
    border-radius: 6px;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {ACCENT};
}}
QLineEdit {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {OUTLINE};
    border-radius: 18px;
    padding: 0 14px;
    min-height: 34px;
    font-size: 13px;
    selection-background-color: {ACCENT};
}}
QLineEdit:focus {{
    border-color: {ACCENT_LIGHT};
}}
QPushButton {{
    background-color: {SURFACE};
    color: {TEXT};
    border: none;
    border-radius: 12px;
    padding: 9px 12px;
    font-size: 13px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {SURFACE_HOVER};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
}}
QPushButton#iconButton {{
    border-radius: 19px;
    padding: 0;
}}
QPushButton#windowButton, QPushButton#closeButton {{
    background-color: transparent;
    border-radius: 14px;
    padding: 0;
}}
QPushButton#windowButton:hover {{
    background-color: {SURFACE_HOVER};
}}
QPushButton#closeButton:hover {{
    background-color: #e5484d;
}}
QPushButton#closeButton:pressed {{
    background-color: #c4383c;
}}
QPushButton#powerButton {{
    background-color: rgba(255, 107, 107, 26);
    border-radius: 22px;
    padding: 0;
}}
QPushButton#powerButton:hover {{
    background-color: rgba(255, 107, 107, 56);
}}
QPushButton#powerButton:pressed {{
    background-color: rgba(255, 107, 107, 96);
}}
QFrame#segment {{
    background-color: {SURFACE};
    border-radius: 14px;
}}
QPushButton#segButton {{
    background-color: transparent;
    border-radius: 11px;
    padding: 0;
}}
QPushButton#segButton:hover {{
    background-color: {SURFACE_HOVER};
}}
QPushButton#segButton:pressed {{
    background-color: {ACCENT};
}}
QPushButton#appButton {{
    border-radius: 10px;
    padding: 3px;
}}
QPushButton#sendButton {{
    background-color: {ACCENT};
    border-radius: 18px;
    padding: 0;
}}
QPushButton#sendButton:hover {{
    background-color: {ACCENT_LIGHT};
}}
QPushButton#sendButton:pressed {{
    background-color: {ACCENT_DARK};
}}
"""

# 24x24 stroke icons. {c} is the colour; filled shapes set fill="{c}".
_ICONS = {
    "power": '<path d="M12 3v8"/><path d="M6.34 7.34A8 8 0 1 0 17.66 7.34"/>',
    "home": '<path d="M4 11.5 12 4l8 7.5"/><path d="M6.5 9.5V20h11V9.5"/><path d="M10 20v-5h4v5"/>',
    "back": '<path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/>',
    "refresh": '<path d="M20 12a8 8 0 1 1-2.34-5.66"/><path d="M20 4v4.5h-4.5"/>',
    "replay": '<path d="M4 12a8 8 0 1 0 2.34-5.66"/><path d="M4 4v4.5h4.5"/>',
    "options": '<path d="M12 5v14"/><path d="M5.94 8.5l12.12 7"/><path d="M5.94 15.5l12.12-7"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "minimize": '<path d="M6 12h12"/>',
    "close": '<path d="M6.5 6.5l11 11"/><path d="M17.5 6.5l-11 11"/>',
    "chevron": '<path d="M6 9l6 6 6-6"/>',
    "send": '<path d="M5 12h14"/><path d="M13 6l6 6-6 6"/>',
    "rewind": '<path fill="{c}" d="M11 6.5 4 12l7 5.5z"/><path fill="{c}" d="M20 6.5 13 12l7 5.5z"/>',
    "forward": '<path fill="{c}" d="M4 6.5 11 12l-7 5.5z"/><path fill="{c}" d="M13 6.5 20 12l-7 5.5z"/>',
    "play_pause": '<path fill="{c}" d="M3.5 6.5 11 12l-7.5 5.5z"/><path d="M15 7v10"/><path d="M19.5 7v10"/>',
    "vol_down": '<path fill="{c}" d="M3 9.5h3.5L11 6v12l-4.5-3.5H3z"/><path d="M15 12h6"/>',
    "vol_up": '<path fill="{c}" d="M3 9.5h3.5L11 6v12l-4.5-3.5H3z"/><path d="M15 12h6"/><path d="M18 9v6"/>',
    "mute": '<path fill="{c}" d="M3 9.5h3.5L11 6v12l-4.5-3.5H3z"/><path d="M15.5 9.5l5 5"/><path d="M20.5 9.5l-5 5"/>',
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


def icon_pixmap(name, color=TEXT, size=18):
    """Render a named icon at 2x so it stays crisp on HiDPI screens."""
    svg = _SVG.format(c=color, body=_ICONS[name].format(c=color))
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return pixmap


def icon(name, color=TEXT, size=18):
    return QIcon(icon_pixmap(name, color, size))


def dot_icon(state):
    pixmap = QPixmap(20, 20)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    color = QColor(LINK_COLORS[state])
    if state != "idle":
        glow = QColor(color)
        glow.setAlpha(70)
        painter.setPen(Qt.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QRectF(0, 0, 20, 20))
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QRectF(4, 4, 12, 12))
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


class Card(QWidget):
    """The window body: a rounded, gradient-filled panel. The top-level
    window is frameless and translucent, so this is all that shows."""

    RADIUS = 20

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill = QLinearGradient(0, 0, 0, rect.height())
        fill.setColorAt(0, QColor(BG_TOP))
        fill.setColorAt(1, QColor(BG_BOTTOM))
        painter.fillPath(path, fill)

        glow = QRadialGradient(QPointF(rect.width() / 2, 0), rect.width() * 0.75)
        glow.setColorAt(0, QColor(150, 80, 230, 60))
        glow.setColorAt(1, QColor(150, 80, 230, 0))
        painter.fillPath(path, glow)

        painter.setPen(QPen(QColor(190, 150, 255, 55), 1))
        painter.drawPath(path)


class DeviceCombo(QComboBox):
    """Pill-shaped device picker with a drawn chevron (the stylesheet hides
    the platform arrow, which doesn't match the rest of the UI) and long
    TV names elided with "…" instead of clipped mid-letter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._chevron = icon_pixmap("chevron", MUTED, 14)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.CC_ComboBox, option)
        field = self.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, self)
        room = field.width() - (self.iconSize().width() + 6 if not option.currentIcon.isNull() else 0)
        option.currentText = self.fontMetrics().elidedText(option.currentText, Qt.ElideRight, room)
        painter.drawControl(QStyle.CE_ComboBoxLabel, option)
        painter.drawPixmap(self.width() - 30, (self.height() - 14) // 2, self._chevron)


class DPad(QWidget):
    """Round Roku-style direction pad: four arrow wedges around an OK
    button, drawn in one widget so the wedges hit-test by angle. Clicks
    outside the disc fall through to the window (so they drag it)."""

    activated = Signal(str)

    WEDGES = {"Up": 45, "Left": 135, "Down": 225, "Right": 315}  # start angles, 90° each

    def __init__(self, diameter=200, parent=None):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self._hover = None
        self._down = None
        self._flash = None
        self._flash_timer = QTimer(self)
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(140)
        self._flash_timer.timeout.connect(self._end_flash)

    @property
    def _center(self):
        return QPointF(self.width() / 2, self.height() / 2)

    @property
    def _radius(self):
        return self.width() / 2 - 2

    @property
    def _ok_radius(self):
        return self._radius * 0.36

    def _region(self, pos):
        dx = pos.x() - self._center.x()
        dy = self._center.y() - pos.y()
        distance = math.hypot(dx, dy)
        if distance > self._radius:
            return None
        if distance <= self._ok_radius:
            return "Select"
        angle = math.degrees(math.atan2(dy, dx)) % 360
        for key, start in self.WEDGES.items():
            if (angle - start) % 360 < 90:
                return key
        return None

    def flash(self, key):
        """Light a region briefly: feedback for keyboard-driven presses."""
        if key == "Select" or key in self.WEDGES:
            self._flash = key
            self._flash_timer.start()
            self.update()

    def _end_flash(self):
        self._flash = None
        self.update()

    def mouseMoveEvent(self, event):
        region = self._region(event.position())
        if region != self._hover:
            self._hover = region
            self.setCursor(Qt.PointingHandCursor if region else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        region = self._region(event.position())
        if event.button() != Qt.LeftButton or not region:
            event.ignore()
            return
        self._down = region
        self.update()

    def mouseReleaseEvent(self, event):
        if not self._down:
            event.ignore()
            return
        if self._region(event.position()) == self._down:
            self.activated.emit(self._down)
        self._down = None
        self.update()

    def _lit(self, region):
        return region in (self._down, self._flash)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        c, r, ok_r = self._center, self._radius, self._ok_radius

        ring = QLinearGradient(0, c.y() - r, 0, c.y() + r)
        ring.setColorAt(0, QColor(ACCENT_LIGHT))
        ring.setColorAt(1, QColor(ACCENT_DARK))
        painter.setPen(QPen(QColor(255, 255, 255, 45), 1))
        painter.setBrush(ring)
        painter.drawEllipse(c, r, r)

        hole = QPainterPath()
        hole.addEllipse(c, ok_r + 5, ok_r + 5)
        disc = QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r)
        painter.setPen(Qt.NoPen)
        for key, start in self.WEDGES.items():
            if self._lit(key):
                shade = QColor(255, 255, 255, 70)
            elif key == self._hover:
                shade = QColor(255, 255, 255, 28)
            else:
                continue
            wedge = QPainterPath(c)
            wedge.arcTo(disc, start, 90)
            wedge.closeSubpath()
            painter.fillPath(wedge.subtracted(hole), shade)

        # Grooves between the wedges.
        painter.setPen(QPen(QColor(20, 6, 40, 90), 2, Qt.SolidLine, Qt.RoundCap))
        for angle in (45, 135, 225, 315):
            rad = math.radians(angle)
            unit = QPointF(math.cos(rad), -math.sin(rad))
            painter.drawLine(c + unit * (ok_r + 10), c + unit * (r - 8))

        # Arrows.
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(TEXT))
        mid = (r + ok_r) / 2 + 2
        for angle in (90, 180, 270, 0):
            rad = math.radians(angle)
            unit = QPointF(math.cos(rad), -math.sin(rad))
            side = QPointF(-unit.y(), unit.x())
            tip = c + unit * (mid + 7)
            base = c + unit * (mid - 5)
            painter.drawPolygon(QPolygonF([tip, base + side * 8, base - side * 8]))

        # OK button.
        if self._lit("Select"):
            ok_fill = QColor(ACCENT)
        elif self._hover == "Select":
            ok_fill = QColor("#45206e")
        else:
            ok_fill = QColor("#341650")
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1))
        painter.setBrush(ok_fill)
        painter.drawEllipse(c, ok_r, ok_r)
        font = QFont(self.font())
        font.setPixelSize(16)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(TEXT))
        painter.drawText(QRectF(c.x() - ok_r, c.y() - ok_r, 2 * ok_r, 2 * ok_r), Qt.AlignCenter, "OK")
