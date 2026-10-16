"""PyInstaller entry point (the frozen app has no ``python -m flow``)."""

import multiprocessing
import sys

from flow.__main__ import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
