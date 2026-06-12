"""ECP client: discovery, device info, key presses, installed apps,
app icons, app launch, and literal text input."""

import socket
from urllib.parse import quote
from xml.etree import ElementTree

import requests

TIMEOUT = 4

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


def _check(response):
    if response.status_code == 403:
        raise LimitedModeError()
    response.raise_for_status()
    return response


def discover(timeout: float = 3.0) -> list:
    """SSDP-discover Rokus, identified by the address each response came
    from. The LOCATION header is deliberately ignored: Rokus keep serving
    a stale pre-DHCP-move address in it, which is how dead IPs end up
    saved."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    ips = []
    try:
        sock.sendto(SSDP_SEARCH, SSDP_ADDR)
        while True:
            try:
                _, addr = sock.recvfrom(2048)
            except socket.timeout:
                break
            if addr[0] not in ips:
                ips.append(addr[0])
    finally:
        sock.close()
    devices = []
    for ip in ips:
        try:
            devices.append(get_device(ip))
        except requests.RequestException:
            pass
    return devices


def _device_info(ip: str) -> ElementTree.Element:
    xml = _check(requests.get(f"http://{ip}:8060/query/device-info", timeout=TIMEOUT)).text
    return ElementTree.fromstring(xml)


def get_device(ip: str) -> dict:
    tree = _device_info(ip)
    name = tree.findtext("user-device-name") or tree.findtext("friendly-device-name")
    return {"name": name or ip, "ip": ip, "serial": tree.findtext("serial-number")}


def get_power(ip: str) -> bool:
    return _device_info(ip).findtext("power-mode") == "PowerOn"


def send_key(ip: str, key: str):
    _check(requests.post(f"http://{ip}:8060/keypress/{key}", timeout=TIMEOUT))


def get_apps(ip: str) -> list:
    xml = _check(requests.get(f"http://{ip}:8060/query/apps", timeout=TIMEOUT)).text
    tree = ElementTree.fromstring(xml)
    return [{"id": app.get("id"), "name": app.text} for app in tree]


def get_app_icon(ip: str, app_id: str) -> bytes:
    return _check(requests.get(f"http://{ip}:8060/query/icon/{app_id}", timeout=TIMEOUT)).content


def launch_app(ip: str, app_id: str):
    _check(requests.post(f"http://{ip}:8060/launch/{app_id}", timeout=TIMEOUT))


def is_limited_mode(ip: str) -> bool:
    mode = _device_info(ip).findtext("ecp-setting-mode", "default")
    return mode.lower() == "limited"


def send_text(ip: str, text: str):
    for char in text:
        send_key(ip, f"Lit_{quote(char, safe='')}")
