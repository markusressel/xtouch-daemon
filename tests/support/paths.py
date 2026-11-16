"""
Where the files of the repository are, for the tests that read them (e.g. the docs).
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
"""The checkout of the repository."""
DOCS = ROOT / "docs"
