#!/bin/bash
# Install the Claude Code statusline on a new machine.
# Run from the repo root: bash config/install.sh
#
# What it does:
#   1. Copies config/statusline.sh → ~/.claude/statusline.sh
#   2. Prints the statusLine block to add to ~/.claude/settings.json
#      (uses the Git Bash path auto-detected on the current machine)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="$HOME/.claude/statusline.sh"

cp "$SCRIPT_DIR/statusline.sh" "$DEST"
chmod +x "$DEST"
echo "Installed: $DEST"

# Detect Git Bash path on Windows (noop on Linux/Mac)
GIT_BASH=""
for candidate in \
    "/c/Program Files/Git/bin/bash.exe" \
    "/c/Users/$USERNAME/AppData/Local/Programs/Git/bin/bash.exe" \
    "/usr/bin/bash"; do
  [ -x "$candidate" ] && GIT_BASH="$candidate" && break
done

echo ""
echo "Add the following to ~/.claude/settings.json:"
echo ""
if [ -n "$GIT_BASH" ]; then
  # Convert to the Windows-style path Claude Code expects
  WIN_BASH=$(cygpath -w "$GIT_BASH" 2>/dev/null || echo "$GIT_BASH")
  WIN_DEST=$(cygpath -w "$DEST" 2>/dev/null | sed 's|\\|/|g' || echo "$DEST")
  echo "  \"statusLine\": {"
  echo "    \"type\": \"command\","
  echo "    \"command\": \"${WIN_BASH//\\/\\\\} ${WIN_DEST}\","
  echo "    \"padding\": 2"
  echo "  }"
else
  echo "  \"statusLine\": {"
  echo "    \"type\": \"command\","
  echo "    \"command\": \"$DEST\","
  echo "    \"padding\": 2"
  echo "  }"
fi
echo ""
