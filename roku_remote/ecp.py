"""ECP client: discovery, device info, key presses, installed apps,
app icons, app launch, and literal text input."""

import logging
import socket
import time
from urllib.parse import quote
from xml.etree import ElementTree

import requests

TIMEOUT = 4

log = logging.getLogger(__name__)
_last_power = {}  # serial -> last logged power-mode

SSDP_ADDR = ("239.255.255.250", 1900)
SSDP_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDR[0]}:{SSDP_ADDR[1]}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "ST: roku:ecp\r\n"
    "MX: 2\r\n\r\n"
).encode()

LIMITED_MODE_HINT = (
    "TV blocks network control. On the TV: Settings > System > Advanced "
    "system settings > Control by mobile apps > Network access > Default"
)


class LimitedModeError(Exception):
    def __str__(self):
        return LIMITED_MODE_HINT


def _request(method: str, ip: str, path: str) -> requests.Response:
    """Every ECP call goes through here so the debug log records each
    request's outcome and timing: a refused connection, a timeout and a
    different TV answering look very different after the fact."""
    # Literal keypresses are typed text (search terms, passwords): never log them.
    shown = "/keypress/Lit_*" if path.startswith("/keypress/Lit_") else path
    start = time.monotonic()
    try:
        response = requests.request(method, f"http://{ip}:8060{path}", timeout=TIMEOUT)
    except requests.RequestException as exc:
        ms = (time.monotonic() - start) * 1000
        log.warning("%s %s%s failed after %.0f ms: %s: %s", method, ip, shown, ms, type(exc).__name__, exc)
        raise
    ms = (time.monotonic() - start) * 1000
    if response.status_code >= 400:
        log.warning("%s %s%s -> HTTP %d in %.0f ms", method, ip, shown, response.status_code, ms)
        if response.status_code == 403:
            raise LimitedModeError()
        response.raise_for_status()
    else:
        log.debug("%s %s%s -> %d in %.0f ms", method, ip, shown, response.status_code, ms)
    return response


def discover(timeout: float = 3.0) -> list:
    """SSDP-discover Rokus, identified by the address each response came
    from. The LOCATION header is deliberately ignored: Rokus keep serving
    a stale pre-DHCP-move address in it, which is how dead IPs end up
    saved.

    The search is re-sent during the listen window: multicast over
    Wi-Fi drops packets, and a single M-SEARCH regularly misses a Roku
    that's on and answering ECP."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    start = time.monotonic()
    deadline = start + timeout
    resends = [start + 0.5, start + 1.0]
    ips = []
    try:
        sock.sendto(SSDP_SEARCH, SSDP_ADDR)
        while (now := time.monotonic()) < deadline:
            if resends and now >= resends[0]:
                resends.pop(0)
                sock.sendto(SSDP_SEARCH, SSDP_ADDR)
                continue
            sock.settimeout(min([deadline] + resends[:1]) - now)
            try:
                _, addr = sock.recvfrom(2048)
            except socket.timeout:
                continue
            if addr[0] not in ips:
                ips.append(addr[0])
    finally:
        sock.close()
    log.info("SSDP: %d Roku(s) answered: %s", len(ips), ", ".join(ips) or "none")
    devices = []
    for ip in ips:
        try:
            devices.append(get_device(ip))
        except requests.RequestException:
            pass
    return devices


def _device_info(ip: str) -> ElementTree.Element:
    xml = _request("GET", ip, "/query/device-info").text
    return ElementTree.fromstring(xml)


def get_device(ip: str) -> dict:
    tree = _device_info(ip)
    name = tree.findtext("user-device-name") or tree.findtext("friendly-device-name")
    serial = tree.findtext("serial-number")
    # Power-mode transitions (PowerOn / Ready / Suspend…) are logged once
    # each, not on every heartbeat: they're what to line up against a
    # TV that stops answering after sitting idle.
    power = tree.findtext("power-mode")
    if _last_power.get(serial) != power:
        _last_power[serial] = power
        log.info("%s [%s] at %s: power-mode %s", name, serial, ip, power)
    return {"name": name or ip, "ip": ip, "serial": serial}


def get_power(ip: str) -> bool:
    return _device_info(ip).findtext("power-mode") == "PowerOn"


def send_key(ip: str, key: str):
    _request("POST", ip, f"/keypress/{key}")


def get_apps(ip: str) -> list:
    xml = _request("GET", ip, "/query/apps").text
    tree = ElementTree.fromstring(xml)
    return [{"id": app.get("id"), "name": app.text} for app in tree]


def get_app_icon(ip: str, app_id: str) -> bytes:
    return _request("GET", ip, f"/query/icon/{app_id}").content


def launch_app(ip: str, app_id: str):
    _request("POST", ip, f"/launch/{app_id}")


def is_limited_mode(ip: str) -> bool:
    mode = _device_info(ip).findtext("ecp-setting-mode", "default")
    return mode.lower() == "limited"


def send_text(ip: str, text: str):
    for char in text:
        send_key(ip, f"Lit_{quote(char, safe='')}")
