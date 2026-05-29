#!/usr/bin/env python3
"""Neutralized staging patcher (NO-OP).

This file was intentionally replaced with a safe no-op to prevent any
automatic or ad-hoc mutations of generated HTML previews in the repo.

If you need to re-apply the original mutator for a controlled, manual
run, restore `_patch_staging_fixes.py.orig` to `_patch_staging_fixes.py`
and run it locally while reviewing changes before committing.

Safe usage:
  - To inspect the original script: open `_patch_staging_fixes.py.orig`.
  - Do NOT run this file in CI or automated builders.

The neutralized script prints a notice and exits with code 0.
"""
import sys

def main():
    print("_patch_staging_fixes.py is neutralized: no automatic HTML patches will run.")
    print("Original content is preserved in _patch_staging_fixes.py.orig")
    return 0


if __name__ == '__main__':
    sys.exit(main())

