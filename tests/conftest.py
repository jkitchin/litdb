"""Pytest configuration and shared fixtures for litdb tests."""

import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_config(temp_dir, monkeypatch):
    """Mock litdb configuration for testing."""
    config_content = """
[embedding]
model = 'all-MiniLM-L6-v2'
chunk_size = 1000
chunk_overlap = 200

[openalex]
email = "test@example.com"

[llm]
model = "ollama/llama2"
"""
    config_file = temp_dir / "litdb.toml"
    config_file.write_text(config_content)

    # Mock the config root
    monkeypatch.setenv("LITDB_ROOT", str(temp_dir))

    return {
        "root": str(temp_dir),
        "embedding": {
            "model": "all-MiniLM-L6-v2",
            "chunk_size": 1000,
            "chunk_overlap": 200,
        },
        "openalex": {
            "email": "test@example.com",
        },
        "llm": {
            "model": "ollama/llama2",
        },
    }


@pytest.fixture
def sample_work_data():
    """Sample OpenAlex work data for testing."""
    return {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.1021/acscatal.5b00538",
        "title": "Examples of Effective Data Sharing in Scientific Publishing",
        "display_name": "Examples of Effective Data Sharing in Scientific Publishing",
        "publication_year": 2015,
        "type": "article",
        "type_crossref": "journal-article",
        "cited_by_count": 42,
        "authorships": [
            {
                "author": {
                    "id": "https://openalex.org/A5023888391",
                    "display_name": "John Kitchin",
                }
            }
        ],
        "abstract": "This is a sample abstract for testing purposes.",
    }


@pytest.fixture
def sample_json_outputs():
    """Sample JSON outputs from LLMs for testing robust_json_parse."""
    return {
        "clean": '{"1": ["topic1", "topic2"], "2": ["topic3"]}',
        "markdown": '```json\n{"1": ["topic1", "topic2"]}\n```',
        "markdown_no_lang": '```\n{"1": ["topic1", "topic2"]}\n```',
        "numeric_keys": '{1: ["topic1"], 2: ["topic2"]}',  # Unquoted keys
        "mixed": 'Some text before\n{"1": ["topic1"]}\nSome text after',
        "nested": '{"topics": {"1": ["a", "b"], "2": ["c"]}}',
    }


@pytest.fixture
def sample_schema_inputs():
    """Sample schema DSL inputs for testing."""
    return {
        "simple": "name:str, age:int",
        "optional": "name:str, email?:str",
        "defaults": "name:str, city:str=Unknown",
        "complex": "title:str, authors:list, year:int, doi?:str, cited:int=0",
        "types": "name:str, age:int, score:float, active:bool, tags:list",
    }
