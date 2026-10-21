#!/bin/bash
set -euo pipefail
resources="$(cd "$(dirname "$0")" && pwd -P)"
app_dir="$(cd "$resources/../.." && pwd -P)"
if /bin/bash "$resources/install_macos.sh" --app-source "$app_dir" "$@"; then
    printf '\nMaxi setup finished. You can close this terminal window.\n'
else
    printf '\nMaxi setup failed. Review the error above and run this installer again.\n' >&2
    exit 1
fi
