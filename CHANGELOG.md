# Changelog

All notable changes to litdb will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.8] - 2025-10-25

### Added

- **fromtext command**: New command to extract and add academic references from pasted text
  - Uses LLM to parse references from various citation formats
  - Integrates with CrossRef API for DOI matching and validation
  - Supports confidence-based automatic and manual confirmation flows
  - Works with references copied from PDFs, papers, websites, etc.
  - See [FROMTEXT_USAGE.md](./FROMTEXT_USAGE.md) for detailed documentation

- **summary command**: Generate newsletter-style summaries of recent articles
  - Automatically extracts topics from articles using LLM
  - Aggregates topics into 5-10 main themes with subtopics
  - Classifies articles into topics and subtopics
  - Generates narrative summaries for each subtopic with article references
  - Outputs org-mode formatted newsletters
  - Configurable time periods (e.g., "1 week", "2 weeks", "1 month")
  - Supports custom LLM model selection

- **extract command**: Extract tables from PDF files
  - Uses computer vision and ML to identify tables
  - Supports extracting all tables or specific tables by index
  - Returns pandas DataFrames for further processing
  - Multiple output format options

- **schema command**: Extract structured data from documents
  - Define schemas using simple DSL syntax (e.g., "title:str, year:int")
  - Support for optional fields, default values, and type hints
  - Alternative JSON schema format support
  - Works with PDFs, web pages, and other document formats
  - Uses LLM with structured output for accurate extraction

- **Configuration improvements**: Enhanced documentation for litdb.toml
  - Clarified which commands use which configuration sections
  - Added comments explaining the purpose of each config section
  - Documented LiteLLM provider support in [llm] section

### Fixed

- **Security**: Replaced unsafe `eval()` with `ast.literal_eval()` in schema parsing
  - Eliminates code execution vulnerability in extract.py
  - Now only evaluates safe Python literals (strings, numbers, lists, dicts)

- **API compliance**: Updated OpenAlex API calls to use `mailto` parameter instead of `email`
  - Affects multiple modules: cli.py, db.py, openalex.py
  - Ensures proper compliance with OpenAlex API guidelines

- **Code quality**: Fixed multiple linting issues identified by ruff
  - Removed unused imports (os in server.py)
  - Removed unused exception variables
  - Fixed unnecessary f-string prefixes
  - Improved exception handling specificity

### Changed

- **chat.py**: Added `max_tokens` parameter to `get_completion()` function
  - Allows commands like `summary` to request larger token limits for batch processing
  - Defaults to model's default if not specified

### Removed

- **mcp.py**: Removed old MCP implementation (168 lines)
  - Replaced by newer mcp_server.py implementation

### Documentation

- Added "Recent Additions" section to README.org highlighting new features
- Added comprehensive documentation for `fromtext` command
- Added detailed documentation for `summary` command with usage examples
- Added documentation for `extract` and `schema` commands with DSL syntax guide
- Enhanced configuration section with usage notes for each config section
- Created this CHANGELOG.md to track version history

## [Earlier Versions]

### [2.1.7 and earlier]

For changes in earlier versions, please refer to the git commit history:
```bash
git log --oneline
```

Key historical features include:
- Vector search with sentence transformers
- Full-text search with FTS5
- Hybrid search combining vector and full-text
- OpenAlex integration for literature search
- LLM-enhanced search (lsearch command)
- Deep research with gpt-researcher
- Local file indexing (PDF, DOCX, PPTX, notebooks)
- YouTube and audio transcription
- Image search with CLIP
- MCP server for Claude Desktop integration
- Streamlit web app interface
- Emacs integration
- Tagging system
- BibTeX export
- CrossRef integration

---

## How to Update

To upgrade to the latest version:

```bash
pip install --upgrade litdb
```

Or for development version:

```bash
pip install --upgrade git+https://github.com/jkitchin/litdb
```

## Breaking Changes

None in this release. All new features are additive and backward compatible.

## Migration Notes

- If you have custom code using the old `mcp.py`, migrate to `mcp_server.py`
- Update any OpenAlex API calls if you're using the library directly (use `mailto` instead of `email`)
- The security fix in schema parsing should not affect normal usage, but may reject some edge cases that were previously accepted via `eval()`
