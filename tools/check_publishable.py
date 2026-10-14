# -*- coding: utf-8 -*-
"""Refuse to publish this repository if client-identifying material or a credential is present.

The scanner is `oto publishable` (oto/validate/publishable.py), so any repository can run it; this
wrapper keeps the engine's CI and tools/run_gates.sh unchanged.

  python tools/check_publishable.py [--strict]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from oto.validate.publishable import scan  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="fail when no deny terms are configured (use in CI)")
    args = ap.parse_args()
    return scan(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), strict=args.strict)


if __name__ == "__main__":
    sys.exit(main())
