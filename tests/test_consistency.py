"""Consistency tests: code vs docs vs config."""

import re

import pytest

from linglong.config import IngestConfig, LLMConfig, MCPConfig, ScoutConfig
from linglong.mcp.server import _INGEST_TOOLS
from linglong.scout.package import SourcePackage


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# --- Config fields ---

def test_example_yml_has_all_config_fields():
    """Every field in config models should appear in .scout.example.yml."""
    example = _read(".scout.example.yml")
    models = [
        (ScoutConfig, None),
        (LLMConfig, "llm"),
        (IngestConfig, "ingest"),
        (MCPConfig, "mcp"),
    ]
    missing = []
    for model_cls, prefix in models:
        for field_name in model_cls.model_fields:
            if field_name.startswith("_"):
                continue
            if field_name not in example:
                label = f"{prefix}.{field_name}" if prefix else field_name
                missing.append(label)
    assert not missing, f"Missing from .scout.example.yml: {missing}"


# --- MCP tools ---

def test_tool_count_correct():
    """Tool count should match server registration."""
    count = len(_INGEST_TOOLS)
    names = [t.__name__ for t in _INGEST_TOOLS]
    assert count == 7, f"Expected 7 tools, got {count}: {names}"


def test_all_tools_in_docs():
    """Every registered tool should appear in 07-mcp-tools.md."""
    docs = _read("docs/design/07-mcp-tools.md")
    for tool in _INGEST_TOOLS:
        name = tool.__name__
        assert f"## {name}" in docs, f"Tool '{name}' missing ## section in 07-mcp-tools.md"


def test_tool_count_in_readme():
    """README tool table should list all registered tools."""
    readme = _read("docs/README.md")
    for tool in _INGEST_TOOLS:
        name = tool.__name__
        assert name in readme, f"Tool '{name}' missing from docs/README.md"


def test_tool_count_in_06_mcp():
    """06-mcp.md tool list should match registered tools."""
    doc = _read("docs/design/06-mcp.md")
    for tool in _INGEST_TOOLS:
        name = tool.__name__
        assert name in doc, f"Tool '{name}' missing from docs/design/06-mcp.md"


def test_doc_tool_count_number():
    """Documents that state a tool count should match actual count."""
    count = len(_INGEST_TOOLS)
    readme = _read("docs/README.md")
    mcp_doc = _read("docs/design/06-mcp.md")

    for doc_name, doc_src in [("README.md", readme), ("06-mcp.md", mcp_doc)]:
        match = re.search(r"(\d+)\s*(?:个)?\s*工具", doc_src)
        if match:
            assert int(match.group(1)) == count, (
                f"{doc_name} says {match.group(1)} tools, actual: {count}"
            )


# --- SourcePackage ---

def test_package_fields_in_example():
    """SourcePackage fields should match .scout.example.yml packages section."""
    example = _read(".scout.example.yml")
    for field_name in SourcePackage.model_fields:
        assert field_name in example, (
            f"SourcePackage.{field_name} missing from .scout.example.yml"
        )
