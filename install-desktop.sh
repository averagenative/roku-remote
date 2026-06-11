#!/usr/bin/env bash
# Install the AppImage to ~/Applications and register a .desktop entry
# + icon so GNOME search (Super key) finds it.
set -euo pipefail
cd "$(dirname "$0")"

APPIMAGE_DEST="$HOME/Applications/roku-remote-x86_64.AppImage"
ICON_DEST="$HOME/.local/share/icons/hicolor/256x256/apps/roku-remote.png"
DESKTOP_DEST="$HOME/.local/share/applications/roku-remote.desktop"

mkdir -p "$HOME/Applications" "$(dirname "$ICON_DEST")" "$(dirname "$DESKTOP_DEST")"
cp roku-remote-x86_64.AppImage "$APPIMAGE_DEST"
chmod +x "$APPIMAGE_DEST"
cp assets/roku-remote.png "$ICON_DEST"

cat > "$DESKTOP_DEST" <<EOF
[Desktop Entry]
Type=Application
Name=Roku Remote
Comment=Control Roku TVs and players on the local network
Exec=$APPIMAGE_DEST
Icon=roku-remote
Terminal=false
Categories=AudioVideo;
Keywords=roku;remote;tv;
StartupWMClass=roku-remote
EOF

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
gtk-update-icon-cache -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "Installed: $DESKTOP_DEST -> $APPIMAGE_DEST"
