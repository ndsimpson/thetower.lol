#!/usr/bin/env python3
"""Check PyPI for newer versions of dependencies listed in pyproject.toml.

Usage: python scripts/check_pypi_updates.py [path/to/pyproject.toml]

Supports PEP 621 (`[project].dependencies`) and Poetry (`[tool.poetry.dependencies]`).
"""
from __future__ import annotations

import json
import sys
import tomllib as toml
import urllib.request
from typing import Dict

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import parse as parse_version


def load_pyproject(path: str) -> dict:
    with open(path, "rb") as f:
        return toml.load(f)


def collect_dependencies(data: dict) -> Dict[str, str]:
    deps: Dict[str, str] = {}

    # PEP 621 - project.dependencies is a list of strings like 'name >=1.2'
    project = data.get("project") or {}
    if project:
        for entry in project.get("dependencies", []) or []:
            if isinstance(entry, str):
                try:
                    req = Requirement(entry)
                    name = req.name
                    spec = str(req.specifier) if req.specifier else ""
                except Exception:
                    import re

                    m = re.match(r"^([A-Za-z0-9_.+-]+)\s*(.*)$", entry)
                    if m:
                        name = m.group(1)
                        spec = m.group(2).strip()
                    else:
                        name = entry
                        spec = ""
                deps[name] = spec

    # Poetry-style - tool.poetry.dependencies (mapping)
    tool = data.get("tool") or {}
    poetry = tool.get("poetry") or {}
    pdeps = poetry.get("dependencies") or {}
    for name, val in (pdeps or {}).items():
        if name == "python":
            continue
        if isinstance(val, str):
            deps[name] = val
        elif isinstance(val, dict) and "version" in val:
            deps[name] = val.get("version", "")
        else:
            deps[name] = ""

    return deps


def fetch_package_info(pkg_name: str) -> dict | None:
    url = f"https://pypi.org/pypi/{pkg_name}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "check-pypi-updates/1.0 (+https://github.com)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        print(f"DEBUG: fetch error for {pkg_name}: {type(e).__name__}: {e}")
        return None


def check_updates(deps: Dict[str, str]) -> None:
    updates = []
    for name, spec in sorted(deps.items(), key=lambda x: x[0].lower()):
        pkg = fetch_package_info(name)
        if pkg is None:
            print(f"{name}: could not fetch info from PyPI")
            continue

        latest = pkg.get("info", {}).get("version")
        if not latest:
            print(f"{name}: could not determine latest version")
            continue

        try:
            latest_v = parse_version(latest)
        except Exception:
            print(f"{name}: invalid latest version '{latest}'")
            continue

        # Build sorted list of available releases (as strings), sorted ascending
        releases = list(pkg.get("releases", {}).keys())
        try:
            releases_sorted = sorted(releases, key=lambda v: parse_version(v))
        except Exception:
            releases_sorted = sorted(releases)

        # Determine current version (if any)
        current_ver: str | None = None
        if not spec:
            current_ver = None
        else:
            s = spec.strip()
            if s.startswith("=="):
                current_ver = s[2:].strip()
            else:
                try:
                    specset = SpecifierSet(s)
                    # find highest release that satisfies the spec
                    satisfying = [v for v in releases_sorted if parse_version(v) in specset]
                    if satisfying:
                        current_ver = satisfying[-1]
                    else:
                        current_ver = None
                except Exception:
                    current_ver = None

        # Collect intermediate versions: > current_ver and <= latest
        intermediate = []
        for v in releases_sorted:
            try:
                pv = parse_version(v)
            except Exception:
                continue
            if pv > latest_v:
                continue
            if current_ver is None:
                # include all up to latest (exclude latest itself)
                if pv < latest_v:
                    intermediate.append(v)
            else:
                try:
                    if pv > parse_version(current_ver) and pv <= latest_v:
                        intermediate.append(v)
                except Exception:
                    continue

        # Only report if there are newer versions beyond current
        if current_ver is None:
            if intermediate:
                updates.append((name, None, latest, intermediate))
        else:
            try:
                if latest_v > parse_version(current_ver):
                    updates.append((name, current_ver, latest, intermediate))
            except Exception:
                updates.append((name, spec, latest, intermediate))

    if not updates:
        print("All dependencies appear up-to-date (based on latest PyPI versions).")
        return

    print("Updates available:")
    for name, cur, latest, inter in updates:
        if cur is None:
            print(f"- {name}: latest {latest} (no constraint in pyproject)")
        else:
            print(f"- {name}: constraint '{cur}' -> latest {latest}")
        if inter:
            # Show up to 20 versions, otherwise show count and range
            if len(inter) <= 20:
                print(f"  Versions between: {', '.join(inter)}")
            else:
                print(f"  {len(inter)} intermediate versions (e.g. {inter[0]} ... {inter[-1]})")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    path = argv[0] if argv else "pyproject.toml"
    try:
        data = load_pyproject(path)
    except FileNotFoundError:
        print(f"Could not open {path}")
        return 2
    deps = collect_dependencies(data)
    if not deps:
        print("No dependencies found in pyproject.toml (supported locations: [project].dependencies, [tool.poetry.dependencies]).")
        return 0
    check_updates(deps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
