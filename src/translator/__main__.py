"""Точка входа команды `python -m src.translator`."""

import sys

from src.translator.cli import main

if __name__ == "__main__":
    sys.exit(main())
