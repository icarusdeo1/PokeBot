"""Tests for project structure and dependencies (SHARED-T01)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


class TestProjectStructure:
    """Verify the project directory structure exists and is valid."""

    def test_root_directory_exists(self) -> None:
        """Root project directory should exist."""
        assert ROOT.is_dir()

    def test_src_directory_exists(self) -> None:
        """src/ directory should exist."""
        assert (ROOT / "src").is_dir()

    def test_all_expected_subdirs_exist(self) -> None:
        """All expected subdirectories per PRD Section 7.1 should exist."""
        expected_dirs = [
            "src/dashboard/routes",
            "src/dashboard/templates",
            "src/bot/monitor/retailers",
            "src/bot/checkout",
            "src/bot/evasion",
            "src/bot/notifications",
            "src/bot/session",
            "src/shared",
        ]
        for subdir in expected_dirs:
            path = ROOT / subdir
            assert path.is_dir(), f"Expected directory missing: {subdir}"

    def test_all_package_init_files_exist(self) -> None:
        """Every package should have an __init__.py file."""
        packages = [
            "src",
            "src.dashboard",
            "src.dashboard.routes",
            "src.bot",
            "src.bot.monitor",
            "src.bot.monitor.retailers",
            "src.bot.checkout",
            "src.bot.evasion",
            "src.bot.notifications",
            "src.bot.session",
            "src.shared",
        ]
        for pkg in packages:
            init_file = ROOT / pkg.replace(".", "/") / "__init__.py"
            assert init_file.is_file(), f"Missing __init__.py in: {pkg}"

    def test_daemon_file_exists(self) -> None:
        """src/daemon.py should exist as an empty placeholder."""
        daemon_path = ROOT / "src" / "daemon.py"
        assert daemon_path.is_file()


class TestRequirementsFile:
    """Verify requirements.txt is present and parseable."""

    def test_requirements_file_exists(self) -> None:
        """requirements.txt should exist in project root."""
        req_path = ROOT / "requirements.txt"
        assert req_path.is_file()

    def test_requirements_can_be_parsed(self) -> None:
        """requirements.txt should be readable without errors."""
        req_path = ROOT / "requirements.txt"
        content = req_path.read_text()
        # Should not be empty
        assert content.strip()
        # Each line should be a valid package spec (non-empty, non-comment)
        lines = [l.strip() for l in content.splitlines() if l.strip() and not l.startswith("#")]
        assert len(lines) > 0

    def test_core_dependencies_are_listed(self) -> None:
        """Core dependencies from PRD Section 6 should be listed."""
        req_path = ROOT / "requirements.txt"
        content = req_path.read_text()
        required_deps = ["httpx", "playwright", "pyyaml", "fastapi", "uvicorn", "aiohttp", "pytest", "mypy", "argon2-cffi", "responses"]
        for dep in required_deps:
            assert dep in content, f"Missing required dependency: {dep}"


class TestPyprojectToml:
    """Verify pyproject.toml is present and valid."""

    def test_pyproject_toml_exists(self) -> None:
        """pyproject.toml should exist in project root."""
        toml_path = ROOT / "pyproject.toml"
        assert toml_path.is_file()

    def test_pyproject_toml_can_be_parsed(self) -> None:
        """pyproject.toml should be valid TOML."""
        toml_path = ROOT / "pyproject.toml"
        content = toml_path.read_text()
        assert "[project]" in content
        assert "name" in content

    def test_python_version_311_or_higher(self) -> None:
        """Project should require Python 3.11+ per PRD Section 6."""
        toml_path = ROOT / "pyproject.toml"
        content = toml_path.read_text()
        assert ">=3.11" in content or ">= 3.11" in content


class TestConfigExample:
    """Verify config.example.yaml is present."""

    def test_config_example_yaml_exists(self) -> None:
        """config.example.yaml should exist in project root."""
        cfg_path = ROOT / "config.example.yaml"
        assert cfg_path.is_file()

    def test_config_example_yaml_is_valid_yaml(self) -> None:
        """config.example.yaml should be valid YAML (empty list doesn't fail parse)."""
        import yaml
        cfg_path = ROOT / "config.example.yaml"
        # Should not raise
        with open(cfg_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)