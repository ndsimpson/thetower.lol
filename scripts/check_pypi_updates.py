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

    # PEP 621 - project.optional-dependencies is a mapping of group -> list of strings
    opt_deps = project.get("optional-dependencies") or {}
    if opt_deps:
        for group, entries in (opt_deps or {}).items():
            for entry in entries or []:
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
                    # include optional deps as well (they may overwrite only if not present)
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


def fetch_package_version_info(pkg_name: str, version: str) -> dict | None:
    """Fetch PyPI JSON metadata for a specific package version (best-effort).

    Returns the JSON object from `/pypi/{name}/{version}/json` or None on error.
    """
    url = f"https://pypi.org/pypi/{pkg_name}/{version}/json"
    req = urllib.request.Request(url, headers={"User-Agent": "check-pypi-updates/1.0 (+https://github.com)"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except Exception as e:
        print(f"DEBUG: fetch version error for {pkg_name}=={version}: {type(e).__name__}: {e}")
        return None


def check_updates(deps: Dict[str, str]) -> None:
    updates = []
    # preserve order from pyproject.toml (insertion order of dict)
    for name, spec in deps.items():
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
                    if pv > parse_version(current_ver) and pv < latest_v:
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
        latest_url = f"https://pypi.org/project/{name}/{latest}/"
        if cur is None:
            print(f"- {name}: latest {latest} (no constraint in pyproject) -> {latest_url}")
        else:
            print(f"- {name}: constraint {cur} -> latest {latest} ({latest_url})")
        if inter:
            # Show up to 20 versions, otherwise show count and range
            if len(inter) <= 20:
                print(f"  Versions between: {', '.join(inter)}")
            else:
                print(f"  {len(inter)} intermediate versions (e.g. {inter[0]} ... {inter[-1]})")

    # Determine one-step candidates and check lightweight compatibility
    # Candidate: the next version after current (first intermediate in list)
    safe_steps: Dict[str, str] = {}
    unsafe_reasons: Dict[str, list[str]] = {}

    for name, cur, latest, inter in updates:
        if not inter:
            # nothing to step to
            continue
        candidate = inter[0]
        pkg = fetch_package_info(name)
        if pkg is None:
            unsafe_reasons.setdefault(name, []).append("could not fetch package metadata for candidate")
            continue

        # Gather candidate requirements from package info if available (best-effort)
        requires = pkg.get("info", {}).get("requires_dist") or []

        # Helper to evaluate environment markers
        from packaging.markers import default_environment

        env = default_environment()

        conflict = False
        reasons: list[str] = []

        for r in requires:
            try:
                req = Requirement(r)
            except Exception:
                # skip unparsable requirement
                continue

            # Skip requirements that don't apply to our environment
            if getattr(req, "marker", None) is not None:
                try:
                    if not req.marker.evaluate(env):
                        continue
                except Exception:
                    # if marker evaluation fails, conservatively keep requirement
                    pass

            dep_name = req.name

            # If the dependency is not in our pyproject (we don't manage it), assume OK
            if dep_name not in deps:
                continue

            local_spec = deps.get(dep_name, "")
            # empty local spec -> we don't constrain it, assume OK
            if not local_spec:
                continue

            # Now check whether there exists any released version of the dependency
            # that satisfies both the package's requirement and our local constraint.
            dep_pkg = fetch_package_info(dep_name)
            if dep_pkg is None:
                conflict = True
                reasons.append(f"dependency {dep_name}: could not fetch metadata to verify {req.specifier}")
                continue

            dep_releases = list(dep_pkg.get("releases", {}).keys())
            try:
                dep_releases_sorted = sorted(dep_releases, key=lambda v: parse_version(v))
            except Exception:
                dep_releases_sorted = sorted(dep_releases)

            try:
                req_spec = req.specifier or SpecifierSet("")
            except Exception:
                req_spec = SpecifierSet("")

            try:
                local_specset = SpecifierSet(local_spec)
            except Exception:
                local_specset = SpecifierSet("")

            intersection_found = False
            for dv in dep_releases_sorted:
                try:
                    pv = parse_version(dv)
                except Exception:
                    continue
                try:
                    if (not req_spec or pv in req_spec) and (not local_specset or pv in local_specset):
                        intersection_found = True
                        break
                except Exception:
                    continue

            if not intersection_found:
                conflict = True
                reasons.append(f"dependency {dep_name} has no release satisfying {req.specifier} and local {local_spec}")

        if not conflict:
            safe_steps[name] = candidate
        else:
            unsafe_reasons[name] = reasons

    # Print safe step results
    if safe_steps:
        print("\nSafe to step (one-step) this round:")
        for n, v in safe_steps.items():
            candidate_url = f"https://pypi.org/project/{n}/{v}/"
            print(f"- {n}: -> {v} ({candidate_url})")
            # Fetch version-specific metadata and show declared requirements that map to our project deps
            ver_meta = fetch_package_version_info(n, v)
            if ver_meta is None:
                print("  (could not fetch metadata for this specific version)")
                continue
            reqs = ver_meta.get("info", {}).get("requires_dist") or []
            matched = []
            for r in reqs:
                try:
                    req = Requirement(r)
                except Exception:
                    continue
                dep_name = req.name
                if dep_name in deps:
                    spec = str(req.specifier) if req.specifier else ""
                    marker = f"; {req.marker}" if getattr(req, "marker", None) is not None else ""
                    matched.append((dep_name, spec, marker))

            if matched:
                print("  Declared requirements affecting project deps:")
                for dep_name, spec, marker in matched:
                    local = deps.get(dep_name) or "<no constraint>"
                    print(f"  - {dep_name}: requires {spec}{marker} (you have: {local})")
            else:
                print("  (no declared requirements that match your project dependencies)")

    if unsafe_reasons:
        print("\nPackages skipped this round due to potential conflicts:")
        for n, rs in unsafe_reasons.items():
            print(f"- {n}: {', '.join(rs)}")


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
