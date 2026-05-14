#!/usr/bin/env python3
"""
Bakkis Studio Vault — entry point.
"""

import sys
import os

# Ensure the project root is on the path regardless of how the app is launched
sys.path.insert(0, os.path.dirname(__file__))

from app.ui.main_window import MainWindow


def main() -> None:
    app = MainWindow()
    app.mainloop()


if __name__ == "__main__":
    main()
