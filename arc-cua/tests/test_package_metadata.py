"""Guard: a future package rename must be reflected consistently in pyproject.toml and the installed dist metadata."""

import tomllib
from importlib.metadata import distribution
from pathlib import Path


def test_installed_package_name_matches_pyproject():
    pyproject_name = tomllib.loads(
        (Path(__file__).resolve().parent.parent / "pyproject.toml").read_text()
    )["project"]["name"]

    assert distribution("arc-cua").metadata["Name"] == pyproject_name
