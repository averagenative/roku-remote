#!/usr/bin/env bash
# Build roku-remote-windows-x86_64.exe locally with Wine + Windows Python.
# Uses the NuGet python package (a plain zip) so no installer runs under
# Wine. The Wine prefix and Python live under build/ and are reused.
set -euo pipefail
cd "$(dirname "$0")"

PYVER=3.12.10
WINPY=build/win-python
PYEXE="$WINPY/tools/python.exe"
export WINEPREFIX="$(pwd)/build/wine"
export WINEDEBUG=-all

if [ ! -f "$PYEXE" ]; then
    mkdir -p "$WINPY"
    curl -fL -o build/python.nupkg "https://globalcdn.nuget.org/packages/python.$PYVER.nupkg"
    python3 -m zipfile -e build/python.nupkg "$WINPY"
    wine "$PYEXE" -m ensurepip --default-pip
fi

# PySide6 is pinned: Qt >= 6.7 links Windows' system icuuc.dll, which Wine
# doesn't provide — newer versions break both this build and the smoke test.
wine "$PYEXE" -m pip install --upgrade --quiet "pyside6==6.6.3.1" controku requests pillow pyinstaller

wine "$PYEXE" -c "from PIL import Image; Image.open('assets/roku-remote.png').save('build/roku-remote.ico', sizes=[(256,256),(128,128),(64,64),(48,48),(32,32),(16,16)])"

wine "$PYEXE" -m PyInstaller --noconfirm --clean --windowed --onefile \
    --name roku-remote \
    --icon "$(pwd)/build/roku-remote.ico" \
    --add-data "$(pwd)/assets/roku-remote.png;." \
    --distpath build/dist-windows --workpath build/work-windows --specpath build/win-spec \
    launcher.py

mv build/dist-windows/roku-remote.exe roku-remote-windows-x86_64.exe
echo "Built $(pwd)/roku-remote-windows-x86_64.exe"
