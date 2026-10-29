"""Start the app with:  python main.py"""
import sys

if sys.version_info < (3, 10):
    sys.exit(
        "ATS Scout needs Python 3.10 or newer, but this is Python "
        f"{sys.version_info.major}.{sys.version_info.minor}.\n"
        "Install a newer Python from https://www.python.org/downloads/ "
        "(macOS with Homebrew: brew install python@3.13 python-tk@3.13), "
        "then delete the 'venv' folder and create it again with the new Python.\n"
        "See the Troubleshooting section of the README."
    )

from ats_scout.app import main

if __name__ == "__main__":
    main()
