#!/usr/bin/env bash
# Build roku-remote-x86_64.AppImage: PyInstaller onedir bundle wrapped
# in an AppDir, squashed with appimagetool.
set -euo pipefail
cd "$(dirname "$0")"

VENV=.venv
APPDIR=build/AppDir
TOOL=build/appimagetool-x86_64.AppImage

"$VENV/bin/pyinstaller" --noconfirm --clean --windowed \
    --name roku-remote \
    --add-data "$(pwd)/assets/roku-remote.png:." \
    --distpath build/dist --workpath build/work --specpath build \
    launcher.py

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
cp -r build/dist/roku-remote/. "$APPDIR/usr/bin/"
cp assets/roku-remote.png "$APPDIR/roku-remote.png"

cat > "$APPDIR/roku-remote.desktop" <<'EOF'
[Desktop Entry]
Type=Application
Name=Roku Remote
Comment=Control Roku TVs and players on the local network
Exec=roku-remote
Icon=roku-remote
Categories=AudioVideo;
EOF

cat > "$APPDIR/AppRun" <<'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/roku-remote" "$@"
EOF
chmod +x "$APPDIR/AppRun"

if [ ! -x "$TOOL" ]; then
    curl -fsSL -o "$TOOL" \
        https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage
    chmod +x "$TOOL"
fi

ARCH=x86_64 "$TOOL" --appimage-extract-and-run "$APPDIR" roku-remote-x86_64.AppImage
echo "Built $(pwd)/roku-remote-x86_64.AppImage"
