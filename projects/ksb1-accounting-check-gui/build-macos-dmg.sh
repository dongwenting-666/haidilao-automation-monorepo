#!/bin/zsh
set -euo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(cd -- "$SCRIPT_DIR/../.." && pwd)
DIST_DIR="$REPO_ROOT/dist"
APP_NAME="KSB1会计检查.app"
DMG_NAME="KSB1会计检查-mac.dmg"
ZIP_NAME="KSB1会计检查-mac.zip"
STAGING_DIR="$DIST_DIR/dmg-staging"
README_FILE="$STAGING_DIR/安装说明.txt"

"$SCRIPT_DIR/build-macos-app.sh"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"
cp -R "$DIST_DIR/$APP_NAME" "$STAGING_DIR/"
ln -s /Applications "$STAGING_DIR/Applications"

cat > "$README_FILE" <<'EOF'
KSB1会计检查 Mac 使用说明

1. 把 “KSB1会计检查.app” 拖到 “Applications”
2. 首次打开如果被 macOS 拦截，请右键应用后选择“打开”
3. 使用前请确认：
   - 已安装 SAP GUI for Java
   - VPN 可连接
   - 账号权限正常
4. 工具自动化的是 KSB1 导出流程，不替代财务判断
EOF

rm -f "$DIST_DIR/$DMG_NAME" "$DIST_DIR/$ZIP_NAME"
if hdiutil create \
  -volname "KSB1会计检查" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DIST_DIR/$DMG_NAME"
then
  PACKAGE_PATH="$DIST_DIR/$DMG_NAME"
else
  echo "hdiutil failed, falling back to zip package..."
  ditto -c -k --sequesterRsrc --keepParent "$STAGING_DIR" "$DIST_DIR/$ZIP_NAME"
  PACKAGE_PATH="$DIST_DIR/$ZIP_NAME"
fi

echo
echo "Built:"
echo "  $DIST_DIR/$APP_NAME"
echo "  $PACKAGE_PATH"
