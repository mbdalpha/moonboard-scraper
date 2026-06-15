#!/usr/bin/env bash
# Backwards-compatible shim: the capture -> fetch -> convert flow now lives in
# the unified CLI. This just forwards to it so the old command keeps working.
#   ./moonboard fetch   (does the same thing, plus more commands)
cd "$(dirname "$0")"
exec ./moonboard fetch "$@"
