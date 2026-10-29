#!/bin/bash
# Double-click launcher for macOS. First run sets everything up, later runs just open the app.
cd "$(dirname "$0")" || exit 1

if [ ! -d venv ]; then
  echo "First run: setting up (needs internet, takes about a minute)..."
  python3 -m venv venv || { echo "Could not create venv. Is Python 3.10+ installed?"; read -n 1 -s -r -p "Press any key to close"; exit 1; }
  source venv/bin/activate
  pip install -q -r requirements.txt || { echo "Install failed."; read -n 1 -s -r -p "Press any key to close"; exit 1; }
else
  source venv/bin/activate
fi

python3 main.py
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "The app closed with an error (see above). If it says _tkinter is missing, run: brew install python-tk@3.14"
  read -n 1 -s -r -p "Press any key to close"
fi
