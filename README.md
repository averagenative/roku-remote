# roku-remote

A Linux desktop Roku remote styled after the Roku phone app: dark purple
theme, D-pad, media/volume keys, channel shortcuts with real app icons,
and keyboard text input. Ships as a single AppImage.

All device control is plain [ECP](https://developer.roku.com/docs/developer-program/dev-tools/external-control-api.md)
over HTTP, implemented in `roku_remote/ecp.py`: SSDP discovery, key
presses, app list/icons/launch, and `Lit_` text input. Everything talks
to port 8060 on the device — no cloud, no account.

Devices are remembered by serial number, so when DHCP moves a Roku to a
new address the app rescans automatically and reconnects instead of
erroring at the stale IP.

## One-time TV setting (important)

TCL/Roku devices ship with ECP in **Limited mode**, which rejects all
network control with `403 ECP command not allowed in Limited mode`.
On each TV/player you want to control:

> Settings > System > Advanced system settings >
> Control by mobile apps > Network access > **Default**

The app shows this hint in its status line whenever it hits the 403.

## Run from source

```
.venv/bin/python -m roku_remote
```

## Build the AppImage

```
./build-appimage.sh
```

Produces `roku-remote-x86_64.AppImage` (PyInstaller onedir + appimagetool).

## Install for GNOME search (Super key)

```
./install-desktop.sh
```

Copies the AppImage to `~/Applications/`, the icon to
`~/.local/share/icons/hicolor/`, and registers
`~/.local/share/applications/roku-remote.desktop`. Re-run after rebuilds.

## Keyboard shortcuts

| Key | Action |
| --- | --- |
| Arrows / Enter | Navigate / OK |
| Backspace, Esc | Back |
| H | Home |
| Space | Play/pause |
| , / . | Rewind / fast-forward |
| - / = | Volume down / up |
| M | Mute |

Shortcuts pause while the text field has focus. Devices are remembered
in `~/.config/roku-remote/`; use ⟳ to re-discover or + to add by IP.

## License

MIT.
