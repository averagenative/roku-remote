"""Roku Remote — a desktop remote styled after the Roku phone app.

All ECP traffic (discovery, device info, keys, apps, text) lives in
ecp.py. All network I/O runs on a QThreadPool so the UI never blocks
on an unreachable TV.
"""

import json
import logging
import logging.handlers
import os
import sys
from pathlib import Path

import requests
from PySide6.QtCore import QObject, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QIcon, QKeySequence, QPixmap, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from . import __version__, ecp, ui

log = logging.getLogger("roku_remote")

# How often to rescan for a selected TV that couldn't be found, so it
# reconnects on its own once it's powered on or back on the network:
# every 10 s for the first minute, then once a minute so a TV that's
# unplugged overnight doesn't mean a scan (and log lines) every 10 s.
# Pressing a remote button while it's searching rescans immediately.
RETRY_MS = 10_000
RETRY_SLOW_MS = 60_000
RETRY_FAST_ATTEMPTS = 6

# How often to re-check the connected TV, so an IP change or deep sleep
# is caught and recovered before the next keypress rather than by it.
HEARTBEAT_MS = 30_000

KEY_HINTS = (
    "Arrows: navigate   Enter: OK   Backspace: back   "
    "H: home   Space: play/pause   ,/.: rew/ff   -/=: volume   M: mute"
)

LINK_TIPS = {
    "ok": "Connected",
    "busy": "Connecting…",
    "lost": "Not found",
    "idle": "Not connected",
}


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
        self._link = "idle"
        self._retries = 0
        self._scanning = False
        self._retry = QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._rescan)
        self._heartbeat = QTimer(self)
        self._heartbeat.setInterval(HEARTBEAT_MS)
        self._heartbeat.timeout.connect(self._check_alive)
        self._heartbeat.start()

        self._build_ui()
        self._bind_keys()
        self._restore_devices()
        if not self.devices:
            self.discover()

    @property
    def ip(self):
        return self.device_box.currentData()

    @property
    def selected(self):
        """The saved entry for the selected combo row. Combo rows mirror
        self.devices in order, so this stays right even when two stale
        entries briefly share an IP."""
        index = self.device_box.currentIndex()
        return self.devices[index] if 0 <= index < len(self.devices) else None

    def _build_ui(self):
        # No system title bar: the window is a frameless, translucent
        # top-level and the rounded Card is everything that's drawn.
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        card = ui.Card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(12)

        # Title bar. Any empty area of the window drags it (mousePressEvent).
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        logo = QLabel()
        if _icon_path().exists():
            pixmap = QPixmap(str(_icon_path())).scaled(40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pixmap.setDevicePixelRatio(2)
            logo.setPixmap(pixmap)
        title = QLabel("Roku Remote")
        title.setObjectName("title")
        title_row.addWidget(logo)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(self._icon_button("minimize", self.showMinimized, "windowButton", "Minimize", 28, 16))
        title_row.addWidget(self._icon_button("close", self.close, "closeButton", "Close (Ctrl+Q)", 28, 16))
        layout.addLayout(title_row)

        device_row = QHBoxLayout()
        device_row.setSpacing(8)
        self.device_box = ui.DeviceCombo()
        self.device_box.setObjectName("deviceBox")
        self.device_box.setItemDelegate(QStyledItemDelegate(self.device_box))
        self.device_box.setIconSize(QSize(10, 10))
        self.device_box.setFocusPolicy(Qt.NoFocus)
        self.device_box.setCursor(Qt.PointingHandCursor)
        self.device_box.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.device_box.currentIndexChanged.connect(self._device_changed)
        device_row.addWidget(self.device_box, stretch=1)
        device_row.addWidget(self._icon_button("refresh", self.discover, "iconButton", "Discover devices", 38, 18))
        device_row.addWidget(self._icon_button("plus", self.add_by_ip, "iconButton", "Add device by IP", 38, 20))
        layout.addLayout(device_row)

        nav = QHBoxLayout()
        nav.setSpacing(10)
        nav.addWidget(self._key_button("Back", "Back", icon="back"))
        nav.addWidget(self._icon_button("power", self.toggle_power, "powerButton", "Power", 44, 20, ui.POWER_RED))
        nav.addWidget(self._key_button("Home", "Home", icon="home"))
        layout.addLayout(nav)

        self.dpad = ui.DPad(200)
        self.dpad.activated.connect(self.send_key)
        pad_row = QHBoxLayout()
        pad_row.addStretch()
        pad_row.addWidget(self.dpad)
        pad_row.addStretch()
        layout.addLayout(pad_row)

        extras = QHBoxLayout()
        extras.setSpacing(10)
        extras.addWidget(self._key_button("Replay", "InstantReplay", icon="replay"))
        extras.addWidget(self._key_button("Options", "Info", icon="options"))
        layout.addLayout(extras)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        controls.addWidget(self._segment([
            ("rewind", "Rev", "Rewind (,)"),
            ("play_pause", "Play", "Play / pause (Space)"),
            ("forward", "Fwd", "Fast-forward (.)"),
        ]), stretch=1)
        controls.addWidget(self._segment([
            ("vol_down", "VolumeDown", "Volume down (-)"),
            ("mute", "VolumeMute", "Mute (M)"),
            ("vol_up", "VolumeUp", "Volume up (=)"),
        ]), stretch=1)
        layout.addLayout(controls)

        # Fixed height so the window doesn't jump when app tiles load.
        apps = QWidget()
        apps.setFixedHeight(40)
        self.apps_row = QHBoxLayout(apps)
        self.apps_row.setContentsMargins(0, 0, 0, 0)
        self.apps_row.setSpacing(6)
        layout.addWidget(apps)

        text_row = QHBoxLayout()
        text_row.setSpacing(8)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("Type to send text to the TV…")
        self.text_input.returnPressed.connect(self.send_text)
        text_row.addWidget(self.text_input, stretch=1)
        text_row.addWidget(self._icon_button("send", self.send_text, "sendButton", "Send text", 36, 18))
        layout.addLayout(text_row)

        self.status = QLabel(KEY_HINTS)
        self.status.setObjectName("statusLabel")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignCenter)
        self.status.setFixedHeight(44)  # three lines: room for the longest hint
        layout.addWidget(self.status)

        # The card holds keyboard focus so the arrow-key shortcuts work at
        # launch; otherwise the text box (first focusable widget) takes it
        # and suspends them.
        card.setFocusPolicy(Qt.ClickFocus)
        self.setCentralWidget(card)
        card.setFocus()
        self.setFixedWidth(360)
        self.adjustSize()
        self.setFixedSize(self.size())

    def _button(self, label, slot, object_name=None, tip=None, icon=None, icon_size=18):
        btn = QPushButton(label)
        if object_name:
            btn.setObjectName(object_name)
        if tip:
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
        if icon:
            btn.setIcon(ui.icon(icon, size=icon_size))
            btn.setIconSize(QSize(icon_size, icon_size))
        btn.clicked.connect(slot)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return btn

    def _icon_button(self, icon, slot, object_name, tip, size, icon_size, color=ui.TEXT):
        btn = self._button("", slot, object_name, tip)
        btn.setIcon(ui.icon(icon, color, icon_size))
        btn.setIconSize(QSize(icon_size, icon_size))
        btn.setFixedSize(size, size)
        return btn

    def _key_button(self, label, key, object_name=None, icon=None):
        btn = self._button(label, lambda: self.send_key(key), object_name, tip=key, icon=icon)
        btn.setFixedHeight(40)
        return btn

    def _segment(self, items):
        """A pill holding a few icon-only key buttons (media, volume)."""
        frame = QFrame()
        frame.setObjectName("segment")
        row = QHBoxLayout(frame)
        row.setContentsMargins(3, 3, 3, 3)
        row.setSpacing(2)
        for icon, key, tip in items:
            btn = self._icon_button(icon, lambda _=False, k=key: self.send_key(k), "segButton", tip, 34, 20)
            btn.setMinimumWidth(0)
            btn.setMaximumWidth(16777215)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            row.addWidget(btn)
        return frame

    def mousePressEvent(self, event):
        # Frameless window: let the compositor move it from any spot that
        # isn't a control (works on Wayland, where apps can't self-position).
        if event.button() == Qt.LeftButton and self.windowHandle():
            self.centralWidget().setFocus()  # clicking off the text box returns keys to the remote
            self.windowHandle().startSystemMove()
            event.accept()
            return
        super().mousePressEvent(event)

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
        for sequence in ("Ctrl+Q", "Ctrl+W"):
            QShortcut(QKeySequence(sequence), self, activated=self.close)
        self.text_input.installEventFilter(self)

    def eventFilter(self, obj, event):
        # The text input owns its keystrokes; suspend remote shortcuts
        # while it has focus so typing isn't hijacked.
        if obj is self.text_input:
            if event.type() == event.Type.KeyPress and event.key() == Qt.Key_Escape:
                self.centralWidget().setFocus()
                return True
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
        names = [d["name"] for d in self.devices]
        for i, device in enumerate(self.devices):
            # Show the IP only when it's needed to tell two TVs apart.
            label = device["name"] if names.count(device["name"]) == 1 else f"{device['name']}  ({device['ip']})"
            self.device_box.addItem(label, device["ip"])
            self.device_box.setItemData(i, device["ip"], Qt.ToolTipRole)
        index = self._index_of({
            "serial": self.settings.value("last_serial"),
            "ip": self.settings.value("last_ip"),
        })
        if index >= 0:
            self.device_box.setCurrentIndex(index)
        self.device_box.blockSignals(False)
        self._set_link(self._link)
        if self.ip:
            self.connect()

    def _set_link(self, state):
        """Connection dot on the selected device in the picker."""
        self._link = state
        current = self.device_box.currentIndex()
        for i in range(self.device_box.count()):
            self.device_box.setItemIcon(i, ui.dot_icon(state if i == current else "idle"))
        device = self.selected
        if device:
            self.device_box.setToolTip(f"{device['name']}\n{device['ip']} · {LINK_TIPS[state]}")

    def _save_devices(self):
        self.settings.setValue("devices", json.dumps(self.devices))

    @staticmethod
    def _same_device(a, b):
        # Serial is the only stable identity: DHCP shuffles IPs, even
        # between the user's own Rokus. IP is the fallback for entries
        # saved before serials were stored.
        if a.get("serial") and b.get("serial"):
            return a["serial"] == b["serial"]
        return bool(a.get("ip")) and a.get("ip") == b.get("ip")

    def _index_of(self, device):
        return next((i for i, d in enumerate(self.devices) if self._same_device(d, device)), -1)

    def _remember_selection(self, device):
        self.settings.setValue("last_serial", device.get("serial") or "")
        self.settings.setValue("last_ip", device["ip"])

    def _device_changed(self):
        self._end_recovery()
        if self.selected:
            log.info("User selected %s", self._describe(self.selected))
            self._remember_selection(self.selected)
            self.connect()

    def connect(self):
        """Re-initiate a connection to the selected device before treating
        it as live. A saved device that's off or gone must not masquerade
        as connected: probe it first, then either confirm and load apps or
        fall into the unreachable-recovery path (via _job_failed)."""
        if not self.ip:
            return
        name = self.device_box.currentText()
        self.set_status(f"Connecting to {name}…", sticky=True)
        want = self.selected
        log.info("Connecting to %s", self._describe(want))
        self._set_link("busy")
        self.run_job(ecp.get_device, self.ip, on_done=lambda device: self._connected(device, want))

    def _connected(self, device, want):
        if want is not self.selected:
            return  # the user picked another device while this probe ran
        if not self._same_device(device, want):
            # A different Roku answered at the saved address: DHCP handed
            # this TV's old IP to another of the user's devices. Don't
            # claim a connection to the wrong TV; rescan to find the
            # right one by serial.
            log.warning("Wrong TV at %s: expected %s, got %s", want["ip"], self._describe(want), self._describe(device))
            self._device_unreachable()
            return
        # Fold in any name/serial drift picked up on reconnect, then
        # show a clear connected state and load the app shortcuts.
        log.info("Connected to %s", self._describe(device))
        self._set_link("ok")
        self._end_recovery()
        self._merge_devices([device])
        self._save_devices()
        self.set_status(f"Connected to {device['name']}")
        self.load_apps()

    def discover(self):
        log.info("Manual rescan requested")
        self._end_recovery()
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
        # The selected entry may get a new IP during the merge; remember it
        # by serial so the rebuilt combo keeps the same device selected.
        selected = self.selected
        new = self._merge_devices(found)
        self._save_devices()
        if selected:
            self._remember_selection(selected)
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
        self.device_box.setCurrentIndex(self._index_of(device))
        self.set_status(f"Added {device['name']}")

    # ---- unreachable-device recovery ----

    def _device_unreachable(self):
        if self._recovering:
            return
        self._recovering = True
        self._retries = 0
        log.warning("Lost %s; rescanning the network", self._describe(self.selected))
        self._set_link("busy")
        name = self.device_box.currentText() or "the TV"
        self.set_status(f"Can't reach {name} — rescanning the network…", sticky=True)
        self._rescan()

    def _rescan(self):
        if self._recovering and not self._scanning:
            self._scanning = True
            self.run_job(ecp.discover, on_done=self._recovery_done, on_failed=self._recovery_failed)

    def _schedule_retry(self):
        self._retries += 1
        delay = RETRY_MS if self._retries <= RETRY_FAST_ATTEMPTS else RETRY_SLOW_MS
        self._retry.start(delay)
        return delay // 1000

    def _end_recovery(self):
        self._recovering = False
        self._retry.stop()

    def _recovery_done(self, found):
        self._scanning = False
        if not self._recovering:
            return  # superseded by a manual rescan or a device switch
        old_ip = self.ip
        log.info("Rescan found: %s", "; ".join(map(self._describe, found)) or "nothing")
        selected, _ = self._apply_discovery(found)
        if selected and any(self._same_device(d, selected) for d in found):
            log.info("Recovered %s (was at %s)", self._describe(selected), old_ip)
            self._end_recovery()
            if selected["ip"] != old_ip:
                self.set_status(f"{selected['name']} moved to {selected['ip']} — reconnecting…")
            else:
                self.set_status(f"{selected['name']} is reachable again — reconnecting…")
        else:
            # Stay latched: _apply_discovery just re-probed the dead IP,
            # and its failure must not start a second scan. Keep retrying
            # so the TV reconnects once it's powered on or back online.
            delay = self._schedule_retry()
            self._set_link("lost")
            log.warning("%s not found (attempt %d); retrying in %d s",
                        self._describe(selected), self._retries, delay)
            self.set_status(
                "TV not found — retrying. Check it's on and connected, or add its new IP (+)",
                sticky=True,
            )

    def _recovery_failed(self, exc):
        self._scanning = False
        if not self._recovering:
            return
        delay = self._schedule_retry()
        self._set_link("lost")
        log.warning("Rescan failed (%s: %s, attempt %d); retrying in %d s",
                    type(exc).__name__, exc, self._retries, delay)
        self.set_status("TV unreachable and network scan failed — retrying…", sticky=True)

    # ---- connection health ----

    def _check_alive(self):
        """Heartbeat: confirm the selected TV still answers at its saved
        IP and is still the same TV (by serial). Silent while healthy;
        on a failure or a different TV answering it starts the normal
        recovery, so the remote already works when the next key is
        pressed instead of failing it."""
        if self._recovering or not self.ip:
            return
        want = self.selected
        self.run_job(
            ecp.get_device, self.ip,
            on_done=lambda device: self._still_alive(device, want),
            on_failed=lambda exc: self._heartbeat_failed(exc, want),
        )

    def _still_alive(self, device, want):
        if want is not self.selected or self._recovering:
            return
        if not self._same_device(device, want):
            log.warning("Heartbeat: wrong TV at %s: expected %s, got %s",
                        want["ip"], self._describe(want), self._describe(device))
            self._device_unreachable()

    def _heartbeat_failed(self, exc, want):
        if want is not self.selected or self._recovering:
            return
        log.warning("Heartbeat failed for %s: %s", self._describe(want), type(exc).__name__)
        if isinstance(exc, (requests.exceptions.ConnectionError, requests.exceptions.Timeout)):
            self._device_unreachable()

    @staticmethod
    def _describe(device):
        if not device:
            return "no device"
        return f"{device.get('name')} [{device.get('serial') or 'no serial'}] at {device.get('ip')}"

    # ---- remote actions ----

    def send_key(self, key):
        if not self._require_device():
            return
        self.dpad.flash(key)
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
        if self._recovering and not self._scanning:
            # The user is trying to use the TV right now: don't make them
            # wait out the retry backoff. The command still goes to the
            # saved IP, which works if the TV is back at the same address.
            log.info("Button pressed while searching; rescanning now")
            self._retry.stop()
            self._rescan()
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
            btn.setFixedSize(49, 38)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setCursor(Qt.PointingHandCursor)
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
        # Args are left out on purpose: send_text's are what the user typed.
        worker.signals.failed.connect(
            lambda exc, name=fn.__name__: log.debug("Job %s failed: %s: %s", name, type(exc).__name__, exc)
        )
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


def log_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    else:
        base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "roku-remote" / "roku-remote.log"


def _setup_logging():
    """Debug log of every ECP request, connection state change and crash,
    rotated at 2 MB with 4 old files kept. A log that can't be written
    (read-only home, odd permissions) must never stop the remote."""
    path = log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(path, maxBytes=2_000_000, backupCount=4, encoding="utf-8")
    except OSError as exc:
        print(f"roku-remote: can't write log at {path}: {exc}", file=sys.stderr)
        return
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger("roku_remote")
    root.setLevel(logging.DEBUG)
    root.addHandler(handler)
    # urllib3's own retry/connection chatter adds nothing _request doesn't.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    def excepthook(kind, value, tb):
        log.critical("Uncaught exception", exc_info=(kind, value, tb))
        sys.__excepthook__(kind, value, tb)

    sys.excepthook = excepthook
    log.info("Roku Remote %s starting (pid %d, %s, log %s)", __version__, os.getpid(), sys.platform, path)


def _icon_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent / "assets"))
    return base / "roku-remote.png"


def main():
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Roku Remote")
    app.setDesktopFileName("roku-remote")
    app.setStyleSheet(ui.STYLE)
    if _icon_path().exists():
        app.setWindowIcon(QIcon(str(_icon_path())))
    window = RemoteWindow()
    window.show()
    code = app.exec()
    log.info("Roku Remote exiting (code %d)", code)
    sys.exit(code)


if __name__ == "__main__":
    main()
