#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec /bin/bash ./scripts/launch.sh "$@"
