#!/usr/bin/env python3
"""Compatibility entry point for collaboration DX packing."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import dx

# Preserve the historical command line: collab-dx-pack.py --out ...
raise SystemExit(dx.main(["pack", *sys.argv[1:]]))