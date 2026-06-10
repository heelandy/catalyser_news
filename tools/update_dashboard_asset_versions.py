#!/usr/bin/env python3
"""
Update or verify dashboard CSS/JS cache-busting hashes in dashboard/index.html.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = ROOT / "dashboard"
INDEX = DASHBOARD / "index.html"
ASSETS = {
    "styles.css": "href",
    "app.js": "src",
}


def asset_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def replace_asset(html: str, asset: str, attr: str, version: str) -> tuple[str, bool]:
    pattern = rf'({attr}="\./{re.escape(asset)})(?:\?v=[^"]*)?(")'
    replacement = rf"\1?v={version}\2"
    updated, count = re.subn(pattern, replacement, html)
    return updated, count > 0


def expected_html() -> str:
    html = INDEX.read_text(encoding="utf-8")
    for asset, attr in ASSETS.items():
        asset_path = DASHBOARD / asset
        if not asset_path.exists():
            raise FileNotFoundError(asset_path)
        html, found = replace_asset(html, asset, attr, asset_hash(asset_path))
        if not found:
            raise RuntimeError(f"{asset} reference not found in {INDEX}")
    return html


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Update/check dashboard asset version hashes.")
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="Rewrite dashboard/index.html with current asset hashes")
    mode.add_argument("--check", action="store_true", help="Fail if dashboard/index.html hashes are stale")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    current = INDEX.read_text(encoding="utf-8")
    expected = expected_html()
    if args.write:
        if current != expected:
            INDEX.write_text(expected, encoding="utf-8")
            print(f"Updated {INDEX}")
        else:
            print(f"{INDEX} already current")
        return
    if current != expected:
        print("Dashboard asset versions are stale. Run:", file=sys.stderr)
        print("python .\\tools\\update_dashboard_asset_versions.py --write", file=sys.stderr)
        raise SystemExit(1)
    print("Dashboard asset versions are current.")


if __name__ == "__main__":
    main()
