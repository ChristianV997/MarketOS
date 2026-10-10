"""Static contract: the Dockerfile's Python base image tracks .python-version.

Pure text parsing; needs no Docker daemon and performs no build.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_FROM_PYTHON = re.compile(r"^\s*FROM\s+(?:--platform=\S+\s+)?python:(\d+)\.(\d+)(?:\.\d+)?(?:[-\s@]|$)", re.I | re.M)


def _major_minor(text: str) -> tuple[int, int]:
    parts = text.strip().split(".")
    return int(parts[0]), int(parts[1])


def _dockerfile_python_versions(dockerfile_text: str) -> list[tuple[int, int]]:
    return [(int(major), int(minor)) for major, minor in _FROM_PYTHON.findall(dockerfile_text)]


def test_dockerfile_python_base_matches_python_version_file():
    declared = _major_minor((ROOT / ".python-version").read_text(encoding="utf-8"))
    found = _dockerfile_python_versions((ROOT / "Dockerfile").read_text(encoding="utf-8"))
    assert found, "Dockerfile declares no `FROM python:<major>.<minor>` base image"
    assert set(found) == {declared}, f"Dockerfile python bases {found} != .python-version {declared}"


def test_parser_detects_drift_and_multi_stage_mismatch():
    assert _dockerfile_python_versions("FROM python:3.14-slim\n") == [(3, 14)]
    assert _dockerfile_python_versions("FROM python:3.12.4-slim AS build\nFROM python:3.13-slim\n") == [(3, 12), (3, 13)]
    assert _dockerfile_python_versions("FROM ubuntu:24.04\n") == []
