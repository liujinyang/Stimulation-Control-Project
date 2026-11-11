#!/bin/bash
# Double-click on a Mac to build "Stimulation Control.app" into ./dist
cd "$(dirname "$0")" || exit 1
set -e
python3 -m venv .venv_build
source .venv_build/bin/activate
pip install --upgrade pip
pip install pyinstaller PySide6 pandas openpyxl pyserial
pyinstaller --noconfirm --clean --distpath dist-macos --workpath build-macos "Stimulation Control.spec"
xattr -cr "dist-macos/Stimulation Control.app" 2>/dev/null || true
echo; echo "Done: $(pwd)/dist-macos/Stimulation Control.app"
read -n 1 -s -r -p "Press any key to close"
