#!/usr/bin/env bash
# Side-by-side diff of two scripts, ignoring comment-only lines and common lines.
# Usage: ./diff.sh file_a file_b
set -euo pipefail

if [ "$#" -ne 2 ]; then
    echo "Usage: $0 <file_a> <file_b>" >&2
    exit 1
fi

colordiff -I '^#' -u  "$1" "$2"
