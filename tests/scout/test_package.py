"""Tests for SourcePackage YAML loading."""

import tempfile
from pathlib import Path

from linglong.scout.package import SourcePackage


def test_package_from_yaml():
    """Load a package from YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_file = Path(tmpdir) / "test.yaml"
        pkg_file.write_text("""
name: "Test Package"
topic: "AI"
""")
        pkg = SourcePackage.from_yaml(pkg_file)
        assert pkg.name == "Test Package"
        assert pkg.topic == "AI"


def test_package_load_all_from_directory():
    """Load all packages from a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_file = Path(tmpdir) / "test.yaml"
        pkg_file.write_text("""
name: "Test"
topic: "test"
""")
        packages = SourcePackage.load_all([tmpdir])
        assert len(packages) == 1
        assert packages[0].name == "Test"


def test_package_creation():
    """Package can be created with name and topic."""
    pkg = SourcePackage(name="default", topic="test")
    assert pkg.name == "default"
    assert pkg.topic == "test"
