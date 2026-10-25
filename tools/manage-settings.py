#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Versioned JSON interface shared by Hyalune Settings and CLI callers."""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent/'src'))
from manager.backend import main
if __name__ == '__main__': raise SystemExit(main())
