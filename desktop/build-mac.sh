#!/usr/bin/env bash
# 在 macOS 上打包成 .app(需 Python3)。产物:dist/帆软报表转换器.app
set -euo pipefail
cd "$(dirname "$0")"

VENV_DIR=".venv"
if [[ ! -x "$VENV_DIR/bin/python" ]]; then
  python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install --disable-pip-version-check -r requirements.txt pyinstaller

# 每次编译:自增 version.py 的 PATCH + 写构建戳 _build.py
VER=$(python ../_bump_and_stamp.py)
echo "🔖 版本:$VER"

rm -rf build dist *.spec

python -m PyInstaller --noconfirm --clean --windowed \
  --name "帆软报表转换器" \
  --icon "assets/icon.icns" \
  --osx-bundle-identifier "com.magicreport.finereport-converter" \
  --collect-all webview \
  --add-data "web:web" \
  --paths ".." \
  --hidden-import convert \
  --hidden-import version \
  --hidden-import _build \
  app.py

echo ""
echo "✅ 完成:dist/帆软报表转换器.app  (v$VER) — 访达里就是单个可双击图标(.app 内部为标准 bundle,拷贝/分发按一个文件处理)。"
echo "   双击即可运行。首次打开若提示「无法验证开发者」:右键 → 打开 → 打开。"
