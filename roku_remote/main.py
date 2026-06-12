"""Roku Remote — a desktop remote styled after the Roku phone app.

All ECP traffic (discovery, device info, keys, apps, text) lives in
ecp.py. All network I/O runs on a QThreadPool so the UI never blocks
on an unreachable TV.
"""

import json
import sys
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from . import ecp

ROKU_PURPLE = "#662d91"
ROKU_PURPLE_LIGHT = "#7b3fae"
ROKU_PURPLE_DARK = "#4a2068"
BACKGROUND = "#17101f"
SURFACE = "#241733"
TEXT = "#f2eefa"

STYLE = f"""
QMainWindow, QDialog {{
    background-color: {BACKGROUND};
}}
QLabel {{
    color: {TEXT};
    font-size: 13px;
}}
QLabel#statusLabel {{
    color: #9b8fb0;
    font-size: 11px;
}}
QComboBox {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {ROKU_PURPLE};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox QAbstractItemView {{
    background-color: {SURFACE};
    color: {TEXT};
    selection-background-color: {ROKU_PURPLE};
}}
QLineEdit {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {ROKU_PURPLE_DARK};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
}}
QLineEdit:focus {{
    border-color: {ROKU_PURPLE_LIGHT};
}}
QPushButton {{
    background-color: {SURFACE};
    color: {TEXT};
    border: none;
    border-radius: 10px;
    padding: 10px;
    font-size: 14px;
}}
QPushButton:hover {{
    background-color: {ROKU_PURPLE_DARK};
}}
QPushButton:pressed {{
    background-color: {ROKU_PURPLE};
}}
QPushButton#padButton {{
    background-color: {ROKU_PURPLE};
    font-size: 20px;
    font-weight: bold;
}}
QPushButton#padButton:hover {{
    background-color: {ROKU_PURPLE_LIGHT};
}}
QPushButton#padButton:pressed {{
    background-color: {ROKU_PURPLE_DARK};
}}
QPushButton#okButton {{
    background-color: {ROKU_PURPLE_DARK};
    font-size: 16px;
    font-weight: bold;
    border-radius: 31px;
}}
QPushButton#okButton:hover {{
    background-color: {ROKU_PURPLE};
}}
QPushButton#powerButton {{
    background-color: {SURFACE};
    color: #e05c5c;
    font-size: 18px;
    border-radius: 18px;
}}
QPushButton#powerButton:hover {{
    background-color: #5c2020;
}}
QPushButton#appButton {{
    background-color: {SURFACE};
    border-radius: 12px;
    padding: 4px;
}}
"""

KEY_HINTS = (
    "Arrows: navigate   Enter: OK   Backspace: back   "
    "H: home   Space: play/pause   ,/.: rew/ff   -/=: volume   M: mute"
)


class Worker(QRunnable):
    """Run a callable on the thread pool, signal result or the exception."""

    class Signals(QObject):
        done = Signal(object)
        failed = Signal(object)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn = fn
        self.args = args
        self.signals = Worker.Signals()

    def run(self):
        try:
            try:
                result = self.fn(*self.args)
            except Exception as exc:
                self.signals.failed.emit(exc)
            else:
                self.signals.done.emit(result)
        except RuntimeError:
            pass  # app shut down while this job was in flight


class RemoteWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Roku Remote")
        self.pool = QThreadPool.globalInstance()
        self.settings = QSettings("roku-remote", "roku-remote")
        self.devices = json.loads(self.settings.value("devices", "[]"))
        self._recovering = False

        self._build_ui()
        self._bind_keys()
        self._restore_devices()
        if not self.devices:
            self.discover()

    @property
    def ip(self):
        return self.device_box.currentData()

    def _build_ui(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(16, 12, 16, 10)
        layout.setSpacing(10)

        top = QHBoxLayout()
        self.power_btn = self._button("⏻", self.toggle_power, "powerButton", "Power")
        self.power_btn.setFixedSize(36, 36)
        title = QLabel("Roku Remote")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        refresh = self._button("⟳", self.discover, tip="Discover devices")
        refresh.setFixedSize(36, 36)
        top.addWidget(self.power_btn)
        top.addStretch()
        top.addWidget(title)
        top.addStretch()
        top.addWidget(refresh)
        layout.addLayout(top)

        device_row = QHBoxLayout()
        self.device_box = QComboBox()
        self.device_box.currentIndexChanged.connect(self._device_changed)
        add_ip = self._button("+", self.add_by_ip, tip="Add device by IP")
        add_ip.setFixedSize(36, 36)
        device_row.addWidget(self.device_box, stretch=1)
        device_row.addWidget(add_ip)
        layout.addLayout(device_row)

        nav = QHBoxLayout()
        nav.addWidget(self._key_button("◁  Back", "Back"))
        nav.addWidget(self._key_button("Home  ⌂", "Home"))
        layout.addLayout(nav)

        pad = QGridLayout()
        pad.setSpacing(6)
        up = self._key_button("▲", "Up", "padButton")
        down = self._key_button("▼", "Down", "padButton")
        left = self._key_button("◀", "Left", "padButton")
        right = self._key_button("▶", "Right", "padButton")
        ok = self._key_button("OK", "Select", "okButton")
        for btn in (up, down, left, right):
            btn.setMinimumSize(62, 62)
        ok.setFixedSize(62, 62)
        pad.addWidget(up, 0, 1)
        pad.addWidget(left, 1, 0)
        pad.addWidget(ok, 1, 1)
        pad.addWidget(right, 1, 2)
        pad.addWidget(down, 2, 1)
        pad_wrap = QHBoxLayout()
        pad_wrap.addStretch()
        pad_wrap.addLayout(pad)
        pad_wrap.addStretch()
        layout.addLayout(pad_wrap)

        extras = QHBoxLayout()
        extras.addWidget(self._key_button("↺ Replay", "InstantReplay"))
        extras.addWidget(self._key_button("＊ Options", "Info"))
        layout.addLayout(extras)

        media = QHBoxLayout()
        media.addWidget(self._key_button("◀◀ Rew", "Rev"))
        media.addWidget(self._key_button("▶ Play/Pause", "Play"))
        media.addWidget(self._key_button("FF ▶▶", "Fwd"))
        layout.addLayout(media)

        volume = QHBoxLayout()
        volume.addWidget(self._key_button("Vol −", "VolumeDown"))
        volume.addWidget(self._key_button("Mute", "VolumeMute"))
        volume.addWidget(self._key_button("Vol +", "VolumeUp"))
        layout.addLayout(volume)

        self.apps_row = QHBoxLayout()
        self.apps_row.setSpacing(6)
        layout.addLayout(self.apps_row)

        text_row = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type to send text to the TV…")
        self.text_input.returnPressed.connect(self.send_text)
        send = self._button("Send", self.send_text)
        text_row.addWidget(self.text_input, stretch=1)
        text_row.addWidget(send)
        layout.addLayout(text_row)

        self.status = QLabel(KEY_HINTS)
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status)

        self.setCentralWidget(root)
        self.setFixedWidth(340)

    def _button(self, label, slot, object_name=None, tip=None):
        btn = QPushButton(label)
        if object_name:
            btn.setObjectName(object_name)
        if tip:
            btn.setToolTip(tip)
        btn.clicked.connect(slot)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return btn

    def _key_button(self, label, key, object_name=None):
        return self._button(label, lambda: self.send_key(key), object_name, tip=key)

    def _bind_keys(self):
        self.shortcuts = []
        bindings = {
            Qt.Key_Up: "Up",
            Qt.Key_Down: "Down",
            Qt.Key_Left: "Left",
            Qt.Key_Right: "Right",
            Qt.Key_Return: "Select",
            Qt.Key_Enter: "Select",
            Qt.Key_Backspace: "Back",
            Qt.Key_Escape: "Back",
            Qt.Key_H: "Home",
            Qt.Key_Space: "Play",
            Qt.Key_Comma: "Rev",
            Qt.Key_Period: "Fwd",
            Qt.Key_Minus: "VolumeDown",
            Qt.Key_Equal: "VolumeUp",
            Qt.Key_M: "VolumeMute",
        }
        for qt_key, roku_key in bindings.items():
            shortcut = QShortcut(QKeySequence(qt_key), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(lambda k=roku_key: self.send_key(k))
            self.shortcuts.append(shortcut)
        self.text_input.installEventFilter(self)

    def eventFilter(self, obj, event):
        # The text input owns its keystrokes; suspend remote shortcuts
        # while it has focus so typing isn't hijacked.
        if obj is self.text_input:
            if event.type() == event.Type.FocusIn:
                for shortcut in self.shortcuts:
                    shortcut.setEnabled(False)
            elif event.type() == event.Type.FocusOut:
                for shortcut in self.shortcuts:
                    shortcut.setEnabled(True)
        return super().eventFilter(obj, event)

    # ---- device management ----

    def _restore_devices(self):
        self.device_box.blockSignals(True)
        self.device_box.clear()
        for device in self.devices:
            self.device_box.addItem(f"{device['name']}  ({device['ip']})", device["ip"])
        last = self.settings.value("last_ip")
        index = self.device_box.findData(last)
        if index >= 0:
            self.device_box.setCurrentIndex(index)
        self.device_box.blockSignals(False)
        if self.ip:
            self.load_apps()

    def _save_devices(self):
        self.settings.setValue("devices", json.dumps(self.devices))

    def _device_changed(self):
        self._recovering = False
        if self.ip:
            self.settings.setValue("last_ip", self.ip)
            self.load_apps()

    def discover(self):
        self._recovering = False
        self.set_status("Searching for Roku devices…")
        self.run_job(ecp.discover, on_done=self._discovered)

    def _merge_devices(self, found):
        """Fold discovery results into the saved list, matching by serial
        first so a TV that moved to a new DHCP address is updated in place
        instead of duplicated. Saved entries from before serials were
        stored match by name before IP: DHCP can shuffle addresses
        *between* the user's own Rokus, so a same-IP match may be a
        different device while a same-name match rarely is. Returns the
        genuinely new devices."""
        new = []
        for device in found:
            serial = device.get("serial")
            legacy = [d for d in self.devices if not d.get("serial")]
            existing = (
                next((d for d in self.devices if serial and d.get("serial") == serial), None)
                or next((d for d in legacy if d["name"] == device["name"]), None)
                or next((d for d in legacy if d["ip"] == device["ip"]), None)
            )
            if existing:
                existing.update(device)
            else:
                self.devices.append(device)
                new.append(device)
        return new

    def _apply_discovery(self, found):
        # The selected entry may get a new IP during the merge; re-point
        # last_ip at it so the rebuilt combo keeps the same device selected.
        selected = next((d for d in self.devices if d["ip"] == self.ip), None)
        new = self._merge_devices(found)
        self._save_devices()
        if selected:
            self.settings.setValue("last_ip", selected["ip"])
        self._restore_devices()
        return selected, new

    def _discovered(self, found):
        if not found:
            self.set_status("No devices found — try adding by IP (+)")
            return
        _, new = self._apply_discovery(found)
        self.set_status(f"Found {len(found)} device(s), {len(new)} new")

    def add_by_ip(self):
        ip, accepted = QInputDialog.getText(self, "Add Roku by IP", "Device IP address:")
        ip = ip.strip()
        if not accepted or not ip:
            return
        self.set_status(f"Checking {ip}…")
        self.run_job(ecp.get_device, ip, on_done=self._ip_added)

    def _ip_added(self, device):
        self._merge_devices([device])
        self._save_devices()
        self._restore_devices()
        self.device_box.setCurrentIndex(self.device_box.findData(device["ip"]))
        self.set_status(f"Added {device['name']}")

    # ---- unreachable-device recovery ----

    def _device_unreachable(self):
        if self._recovering:
            return
        self._recovering = True
        name = self.device_box.currentText() or "the TV"
        self.set_status(f"Can't reach {name} — rescanning the network…", sticky=True)
        self.run_job(ecp.discover, on_done=self._recovery_done, on_failed=self._recovery_failed)

    def _recovery_done(self, found):
        old_ip = self.ip
        selected, _ = self._apply_discovery(found)
        if selected and selected["ip"] != old_ip:
            self._recovering = False
            self.set_status(f"{selected['name']} moved to {selected['ip']} — reconnected, try again")
        elif selected and any(d["ip"] == selected["ip"] for d in found):
            self._recovering = False
            self.set_status(f"{selected['name']} is reachable again — try again")
        else:
            # Stay latched: _apply_discovery just retried load_apps on the
            # dead IP, and its failure must not start another scan.
            self.set_status(
                "TV not found — check it's on and connected, or add its new IP (+)", sticky=True
            )

    def _recovery_failed(self, exc):
        self.set_status("TV unreachable and network scan failed — check your connection", sticky=True)

    # ---- remote actions ----

    def send_key(self, key):
        if not self._require_device():
            return
        self.run_job(ecp.send_key, self.ip, key)

    def toggle_power(self):
        if not self._require_device():
            return
        self.run_job(self._toggle_power, self.ip)

    @staticmethod
    def _toggle_power(ip):
        ecp.send_key(ip, "PowerOff" if ecp.get_power(ip) else "PowerOn")

    def send_text(self):
        text = self.text_input.text()
        if not text or not self._require_device():
            return
        self.text_input.clear()
        self.run_job(ecp.send_text, self.ip, text)

    def _require_device(self):
        if not self.ip:
            self.set_status("No device selected — discover (⟳) or add by IP (+)")
            return False
        return True

    # ---- app shortcuts ----

    def load_apps(self):
        self.run_job(ecp.get_apps, self.ip, on_done=self._apps_loaded)
        self.run_job(ecp.is_limited_mode, self.ip, on_done=self._mode_checked, quiet=True)

    def _mode_checked(self, limited):
        if limited:
            self.set_status(ecp.LIMITED_MODE_HINT, sticky=True)

    def _apps_loaded(self, apps):
        while self.apps_row.count():
            item = self.apps_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        ip = self.ip
        for app in apps[:6]:
            btn = QPushButton()
            btn.setObjectName("appButton")
            btn.setToolTip(app["name"])
            btn.setFixedSize(48, 36)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.clicked.connect(lambda _=False, a=app: self.launch_app(a))
            self.apps_row.addWidget(btn)
            self.run_job(
                ecp.get_app_icon, ip, app["id"],
                on_done=lambda data, b=btn: self._set_app_icon(b, data),
                quiet=True,
            )

    def _set_app_icon(self, btn, data):
        pixmap = QPixmap()
        if pixmap.loadFromData(data):
            btn.setIcon(QIcon(pixmap))
            btn.setIconSize(btn.size() * 0.85)

    def launch_app(self, app):
        if not self._require_device():
            return
        self.set_status(f"Launching {app['name']}…")
        self.run_job(ecp.launch_app, self.ip, app["id"])

    # ---- plumbing ----

    def run_job(self, fn, *args, on_done=None, on_failed=None, quiet=False):
        worker = Worker(fn, *args)
        if on_done:
            worker.signals.done.connect(on_done)
        if on_failed:
            worker.signals.failed.connect(on_failed)
        elif not quiet:
            worker.signals.failed.connect(self._job_failed)
        worker.setAutoDelete(True)
        self._hold = getattr(self, "_hold", [])
        self._hold.append(worker.signals)
        worker.signals.done.connect(lambda *_: self._hold.remove(worker.signals))
        worker.signals.failed.connect(lambda *_: self._hold.remove(worker.signals))
        self.pool.start(worker)

    def _job_failed(self, exc):
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            self._device_unreachable()
        else:
            self.set_status(f"Error: {exc!s}" if str(exc) else f"Error: {type(exc).__name__}", sticky=True)

    def set_status(self, message, sticky=False):
        self.status.setText(message)
        if not sticky:
            QTimer.singleShot(6000, lambda: self.status.text() == message and self.status.setText(KEY_HINTS))


def _icon_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "assets"))
    return base / "roku-remote.png"


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Roku Remote")
    app.setDesktopFileName("roku-remote")
    app.setStyleSheet(STYLE)
    if _icon_path().exists():
        app.setWindowIcon(QIcon(str(_icon_path())))
    window = RemoteWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
