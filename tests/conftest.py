"""Make the package importable when the suite runs without an install.

CI installs the package, which is the proper fix. This keeps a plain `pytest` working from any
directory during development, so a test never passes or fails because of the current directory.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

# The suite must see only the shipped ontologies, never whatever the developer keeps in ~/.oto.
os.environ.setdefault("OTO_ONTOLOGIES", os.path.join(REPO_ROOT, ".no-user-ontologies"))
