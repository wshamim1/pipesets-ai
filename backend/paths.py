"""
Where the backend finds its code files and keeps its data.

CODE_DIR  read-only files shipped with the backend (alembic.ini, migrations/, data/).
          The backend folder, or PyInstaller's unpack dir (sys._MEIPASS) when frozen.
DATA_DIR  writable state: the SQLite DB, the secrets master key, uploads and an optional
          .env. Set by PIPESETS_DATA_DIR (the desktop app points it at the OS app-data
          folder); defaults to the backend folder, so the web / dev setup is unchanged.
"""

import os
import sys

CODE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.abspath(os.path.expanduser(
    os.getenv("PIPESETS_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))
))
os.makedirs(DATA_DIR, exist_ok=True)


def data_path(*parts: str) -> str:
    """A path inside DATA_DIR."""
    return os.path.join(DATA_DIR, *parts)
