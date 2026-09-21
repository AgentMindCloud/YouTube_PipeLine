#!/usr/bin/env python3
"""yt-pipeline entry point.  Try:  python run.py --help"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ytpipeline.cli import main

if __name__ == "__main__":
    main()
