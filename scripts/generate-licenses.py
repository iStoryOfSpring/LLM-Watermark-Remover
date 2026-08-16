#!/usr/bin/env python3
"""Generate a release attribution manifest from the locked Python/npm assets."""

from __future__ import annotations

import argparse
import json
import re
from collections import deque
from importlib import metadata
from pathlib import Path, PurePosixPath

from packaging.markers import default_environment
from packaging.requirements import Requirement


ROOT = Path(__file__).resolve().parents[1]
TEXT_ROOT = ROOT / "LICENSES" / "texts"
PYTHON_REQUIREMENTS = ROOT / "packaging" / "requirements-macos-arm64.txt"
PACKAGE_LOCK = ROOT / "frontend" / "package-lock.json"


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-").lower()


def installed_distributions() -> dict[str, metadata.Distribution]:
    return {
        (dist.metadata.get("Name") or "").lower().replace("_", "-"): dist
        for dist in metadata.distributions()
        if dist.metadata.get("Name")
    }


def root_python_requirements() -> list[Requirement]:
    roots: list[Requirement] = []
    for line in PYTHON_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        roots.append(Requirement(line))
    return roots


def dependency_closure(dists: dict[str, metadata.Distribution]) -> tuple[list[metadata.Distribution], list[str]]:
    roots = root_python_requirements()
    environment = default_environment()
    queue = deque((requirement.name, tuple(sorted(requirement.extras))) for requirement in roots)
    visited: set[tuple[str, tuple[str, ...]]] = set()
    missing_roots = sorted(
        requirement.name for requirement in roots if requirement.name.lower().replace("_", "-") not in dists
    )
    result_by_name: dict[str, metadata.Distribution] = {}
    while queue:
        name, extras = queue.popleft()
        normalized = name.lower().replace("_", "-")
        visit_key = (normalized, extras)
        if visit_key in visited:
            continue
        visited.add(visit_key)
        dist = dists.get(normalized)
        if dist is None:
            continue
        result_by_name[normalized] = dist
        for raw_requirement in dist.requires or []:
            try:
                requirement = Requirement(raw_requirement)
            except Exception:
                continue
            if requirement.marker:
                marker_text = str(requirement.marker)
                if "extra" in marker_text:
                    if not extras or not any(
                        requirement.marker.evaluate({**environment, "extra": extra}) for extra in extras
                    ):
                        continue
                elif not requirement.marker.evaluate(environment):
                    continue
            if requirement.name.lower().replace("_", "-") in dists:
                queue.append((requirement.name, tuple(sorted(requirement.extras))))
    result = sorted(result_by_name.values(), key=lambda item: (item.metadata.get("Name") or "").lower())
    return result, missing_roots


def candidate_license_files(dist: metadata.Distribution) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    paths: dict[str, Path] = {}
    for item in dist.files or []:
        paths[str(item)] = Path(dist.locate_file(item))
    # Recent wheels install license payloads under *.dist-info/licenses but
    # may omit those files from the public ``Distribution.files`` list.
    dist_info = Path(getattr(dist, "_path", ""))
    if dist_info.is_dir():
        for path in dist_info.rglob("*"):
            if path.is_file():
                paths.setdefault(str(path.relative_to(dist_info)), path)

    for source, path in sorted(paths.items()):
        name = PurePosixPath(source).name.lower()
        if not (
            name.startswith("license")
            or name.startswith("licence")
            or name.startswith("copying")
            or name.startswith("notice")
        ):
            continue
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            candidates.append((source, text))
    unique: dict[str, str] = {}
    for source, text in candidates:
        unique.setdefault(text, source)
    return [(source, text) for text, source in unique.items()]


def python_license(dist: metadata.Distribution) -> tuple[str, list[tuple[str, str]]]:
    expression = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "UNKNOWN"
    expression = expression.strip()
    if "\n" in expression or len(expression) > 120:
        expression = "SEE LICENSE FILE"
    files = candidate_license_files(dist)
    if not files:
        files = [
            (
                "METADATA",
                f"License metadata: {expression}\nProject: {dist.metadata.get('Home-page') or dist.metadata.get('Project-URL') or 'unknown'}",
            )
        ]
    return expression.strip() or "UNKNOWN", files


def write_text(package: str, version: str, source: str, text: str, index: int) -> str:
    filename = f"{slug(package)}-{slug(version)}-{index}-{slug(Path(source).stem) or 'license'}.txt"
    target = TEXT_ROOT / filename
    target.write_text(text.rstrip() + "\n", encoding="utf-8")
    return target.relative_to(ROOT).as_posix()


def node_license_entries() -> list[dict[str, str]]:
    lock = json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    entries: list[dict[str, str]] = []
    for package_path, package in sorted(lock.get("packages", {}).items()):
        if not package_path.startswith("node_modules/") or not package.get("version"):
            continue
        package_name = package_path.removeprefix("node_modules/")
        license_name = str(package.get("license") or "UNKNOWN")
        package_dir = ROOT / "frontend" / package_path
        files: list[tuple[str, str]] = []
        if package_dir.is_dir():
            for candidate in sorted(package_dir.iterdir()):
                if not candidate.is_file():
                    continue
                lowered = candidate.name.lower()
                if lowered.startswith(("license", "copying", "notice")):
                    files.append((candidate.name, candidate.read_text(encoding="utf-8", errors="replace")))
        if not files:
            files = [("package.json", f"License metadata: {license_name}\nPackage: {package_name}\n")]
        paths = [write_text(package_name, str(package["version"]), source, text, index) for index, (source, text) in enumerate(files, 1)]
        entries.append({
            "name": package_name,
            "version": str(package["version"]),
            "license": license_name,
            "source": "frontend/package-lock.json",
            "texts": ", ".join(f"`{path}`" for path in paths),
        })
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "LICENSES" / "THIRD_PARTY_NOTICES.md")
    args = parser.parse_args()

    TEXT_ROOT.mkdir(parents=True, exist_ok=True)
    for previous in TEXT_ROOT.glob("*.txt"):
        previous.unlink()

    dists = installed_distributions()
    python_dists, missing = dependency_closure(dists)
    python_entries: list[dict[str, str]] = []
    for dist in python_dists:
        name = dist.metadata.get("Name") or "unknown"
        license_name, files = python_license(dist)
        paths = [write_text(name, dist.version, source, text, index) for index, (source, text) in enumerate(files, 1)]
        python_entries.append({
            "name": name,
            "version": dist.version,
            "license": license_name,
            "source": "Python wheel metadata",
            "texts": ", ".join(f"`{path}`" for path in paths),
        })

    node_entries = node_license_entries()
    lines = [
        "# Third-party notices",
        "",
        "This file is generated by `scripts/generate-licenses.py`. The project code is licensed under Apache-2.0; each bundled component below retains its own license.",
        "",
        "## Project and model",
        "",
        "- LLM Watermark Remover — Copyright 2026 Chen Siyu — Apache-2.0 — `LICENSE`",
        "- Qwen3.5-2B — Apache-2.0 — original files: `model/Qwen3.5-2B/LICENSE` and `model/Qwen3.5-2B/README.md`",
        "",
        "## Python runtime and packaging components",
        "",
        "| Package | Version | Declared license | License text |",
        "| --- | --- | --- | --- |",
    ]
    for entry in python_entries:
        lines.append(f"| {entry['name']} | {entry['version']} | {entry['license']} | {entry['texts']} |")
    lines.extend([
        "",
        "## Frontend dependency tree",
        "",
        "| Package | Version | Declared license | License text |",
        "| --- | --- | --- | --- |",
    ])
    for entry in node_entries:
        lines.append(f"| {entry['name']} | {entry['version']} | {entry['license']} | {entry['texts']} |")
    lines.extend([
        "",
        "## Dictionary source references",
        "",
        "- `jieba` is bundled and listed in the Python table above.",
        "- HanLP and Baidu LAC are documented as source references for the protected-term dictionary; their runtimes are not bundled in this desktop package.",
    ])
    if missing:
        lines.extend([
            "",
            "## Missing build-environment metadata",
            "",
            "The following dependency names were referenced but were not installed when this manifest was generated; the release build must not be published until they are resolved:",
            "",
            *[f"- `{name}`" for name in missing],
        ])
    args.output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.output}")
    print(f"Python packages: {len(python_entries)}; frontend packages: {len(node_entries)}")
    if missing:
        print("Missing Python metadata:", ", ".join(missing))


if __name__ == "__main__":
    main()
