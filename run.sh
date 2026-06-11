#!/usr/bin/env bash
# Wrapper that provides Playwright (patched for NixOS) and runs the puller.
cd "$(dirname "$0")"
exec nix-shell -p "python3.withPackages (p: [p.playwright])" \
  --run "python3 pull_moonboard.py $*"
