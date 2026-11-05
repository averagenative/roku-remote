#!/usr/bin/env bash
# Build roku-remote-x86_64.AppImage: PyInstaller onedir bundle wrapped
# in an AppDir, squashed with appimagetool.
#
# The build runs inside an AlmaLinux 8 distrobox (glibc 2.28), because an
# AppImage only runs on systems whose glibc is at least as new as the one
# it was built against. Built on the Fedora 44 host it needed glibc 2.43
# and failed on Ubuntu 24.04, Debian, and Mint. AlmaLinux 8 is also the
# base of PyPI's manylinux_2_28 wheels, so Qt and the bundled libraries
# match. The box is created and provisioned on first use.
#
# NATIVE=1 ./build-appimage.sh builds on the host with .venv instead: faster,
# but the result only runs on systems as new as the host. Local testing only.
set -euo pipefail
cd "$(dirname "$0")"

BOX=roku-remote-build
BOX_IMAGE=docker.io/library/almalinux:8
# Newest PySide6 with manylinux_2_28 wheels; 6.10 and later need glibc 2.34.
PYSIDE6=6.9.3

if [ "${NATIVE:-0}" != 1 ] && [ -z "${CONTAINER_ID:-}" ]; then
    if ! command -v distrobox >/dev/null; then
        echo "distrobox not found. Install it, or run NATIVE=1 $0 for a host-only build." >&2
        exit 1
    fi
    if ! podman container exists "$BOX" 2>/dev/null; then
        distrobox create --yes --no-entry --name "$BOX" --image "$BOX_IMAGE"
    fi
    exec distrobox enter "$BOX" -- "$PWD/build-appimage.sh" "$@"
fi

if [ "${NATIVE:-0}" = 1 ]; then
    VENV=.venv
else
    VENV="build/venv-$CONTAINER_ID"
    if [ ! -x "$VENV/bin/pyinstaller" ]; then
        # Qt's X11, Wayland, and font libraries must be present so that
        # PyInstaller bundles them for systems that lack them.
        sudo dnf install -y epel-release
        sudo dnf install -y python3.12 python3.12-pip binutils file \
            libxkbcommon libxkbcommon-x11 libxcb libX11 libX11-xcb \
            xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil xcb-util-cursor \
            fontconfig freetype dbus-libs glib2 \
            libwayland-client libwayland-cursor libwayland-egl mesa-libEGL mesa-libGL
        python3.12 -m venv "$VENV"
        "$VENV/bin/pip" install --upgrade pip
        "$VENV/bin/pip" install "pyside6==$PYSIDE6" requests pyinstaller
    fi
fi

APPDIR=build/AppDir
TOOL=build/appimagetool-x86_64.AppImage

"$VENV/bin/pyinstaller" --noconfirm --clean --windowed \
    --name roku-remote \
    --add-data "$(pwd)/assets/roku-remote.png:." \
    --distpath build/dist --workpath build/work --specpath build \
    launcher.py

# Drop Qt plugins the remote doesn't use. The GTK3 theme plugin would link
# the host's GTK against the bundle's older GLib (a runtime crash risk),
# and the PDF image plugin needs libatomic, which isn't bundled. The app
# draws its own style, so neither changes how it looks.
INTERNAL=build/dist/roku-remote/_internal
rm -f "$INTERNAL/PySide6/Qt/plugins/platformthemes/libqgtk3.so" \
    "$INTERNAL/PySide6/Qt/plugins/imageformats/libqpdf.so" \
    "$INTERNAL/PySide6/Qt/lib/libQt6Pdf.so.6" \
    "$INTERNAL/libQt6Pdf.so.6"

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

# Report the oldest glibc this AppImage needs, so a host-built bundle or a
# library pulled in from a newer system doesn't slip into a release.
# objdump fails on the non-ELF files that match *.so* (.hmac checksums).
GLIBC_FLOOR=$( { find "$APPDIR" -type f \( -name '*.so*' -o -name roku-remote \) -exec objdump -T {} + 2>/dev/null || true; } \
    | grep -oE 'GLIBC_[0-9]+\.[0-9]+' | sort -t. -k2 -n -u | tail -1)
echo "Built $(pwd)/roku-remote-x86_64.AppImage (needs ${GLIBC_FLOOR/_/ } or newer)"
