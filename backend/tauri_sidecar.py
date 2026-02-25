#!/usr/bin/env python3
"""Entry point for PyInstaller-bundled Tauri sidecar.

Accepts same args as narrative_mirror.cli_json (e.g. --db data/mirror.db stdio).
"""
import sys
import os

# Ensure narrative_mirror package is importable (for PyInstaller bundle)
_script_dir = os.path.dirname(os.path.abspath(__file__))
_src = os.path.join(_script_dir, "src")
if _src not in sys.path:
    sys.path.insert(0, _src)

from narrative_mirror.cli_json import main

if __name__ == "__main__":
    main()
