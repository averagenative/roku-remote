"""Extra ECP endpoints that controku doesn't cover: installed apps,
app icons, app launch, and literal text input."""

from urllib.parse import quote
from xml.etree import ElementTree

import requests

TIMEOUT = 4

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
    xml = _check(requests.get(f"http://{ip}:8060/query/device-info", timeout=TIMEOUT)).text
    mode = ElementTree.fromstring(xml).findtext("ecp-setting-mode", "default")
    return mode.lower() == "limited"


def send_text(ip: str, text: str):
    for char in text:
        send_key(ip, f"Lit_{quote(char, safe='')}")
