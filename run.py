#!/usr/bin/env python3
"""اجرای ربات:  python run.py"""
import asyncio
import sys

from app.bot import main

if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(0)
