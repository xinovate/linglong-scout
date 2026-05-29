"""Tests for SourcePackage YAML loading."""

import tempfile
from pathlib import Path

from linglong.scout.package import SearchQueryConfig, SourcePackage


def test_load_package_with_search_queries():
    """Load a package with search queries."""
    package = SourcePackage(
        name="test-brief",
        topic="AI 早报",
        search_queries=[
            SearchQueryConfig(keywords=["OpenAI news 2026", "Anthropic latest"], max_results=5),
        ],
    )
    assert package.name == "test-brief"
    assert len(package.search_queries) == 1


def test_package_from_yaml():
    """Load a package from YAML file."""
    with tempfile.TemporaryDirectory() as tmpdir:
        pkg_file = Path(tmpdir) / "test.yaml"
        pkg_file.write_text("""
name: "Test Package"
topic: "AI"
search_queries:
  - keywords:
      - "OpenAI news"
      - "Anthropic Claude"
    max_results: 3
""")
        pkg = SourcePackage.from_yaml(pkg_file)
        assert pkg.name == "Test Package"
        assert len(pkg.search_queries) == 1
        assert pkg.search_queries[0].max_results == 3


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


def test_package_defaults():
    """Package has sensible defaults."""
    pkg = SourcePackage(name="default", topic="test")
    assert pkg.search_queries == []
