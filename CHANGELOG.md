# Changelog

All notable changes to litdb will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **MCP server**: `litdb_mcp` failed to import on fresh installs because the `fastmcp` dependency pulled in `mcp` 2.x, which removed `mcp.server.fastmcp`. litdb now depends on `mcp>=1.22,<2` directly.
- **NSF COA generation**: `nameparser` 3.0 (released 2026-11-08) removed `HumanName`, which `coa.py` and `doe_collaborators.py` use, so fresh installs failed on COA generation. Pinned `nameparser<3`.
- **OpenAlex**: on a network failure (including exhausted retries on 429/5xx), `get_data` returned `None`, so callers crashed with an unhelpful `TypeError`; it now prints the reason and re-raises the request error
- **`litdb suggest-reviewers`**: the list of matching papers printed the literal word "source" instead of each paper's source
- **`update-filters`**: a filter that fails (e.g. OpenAlex is unreachable) is now reported and skipped, keeping its `last_updated` date so the next run retries the same window; previously a bare `except` hid the error and swallowed Ctrl-C
- **YouTube transcripts**: closed a leaked file descriptor from `tempfile.mkstemp`

- **hybrid-search**: results were ranked in reverse (worst match first), full-text scores were normalized with the vector-score range, a source missing from one list counted as a perfect match there, and `-n 1` (or equal scores) crashed with `ZeroDivisionError`. Scores are now normalized per list and summed, higher is better, and at most `n` results are returned.

### Changed

- Declared `requires-python = ">=3.11"`, matching the CI test matrix
- Refreshed `uv.lock` (transformers 5, sentence-transformers 6, pandas 3, langchain-core 1, docling 2.150, pillow 13, torch 2.15)
- Moved `ruff` from runtime dependencies to a `dev` dependency group
- Upgraded ruff to 0.17.5 (lock and pre-commit) and fixed its findings; broad `except Exception` handlers are narrowed or annotated, with per-file ignores only for the Streamlit app and MCP server boundaries
- Removed the Python 2-era `docx` package from the `research` and `all` extras; it installed into the same `docx` module as `python-docx`
- Moved developer notes out of the repository root: `REFACTORING_PLAN.md`, `deep-research.org`, and the Semantic Scholar `swagger.json` are now in `docs/`, and `test_fromtext.sh` is in `scripts/`

### Removed

- Purged `sandbox/` (including a committed Box `.env`), a personal data spreadsheet, and `.claude/settings.local.json` files from the git history. The leaked Box app has been deleted.

### Documentation

- README: added CI, PyPI, and downloads badges; replaced the static test-count badge
- README: serve the DOI badge from shields.io; GitHub's image proxy could not load Zenodo's badge, so it showed as a broken image

## [2.2.3] - 2026-10-27

### Added

- The litdb skill and MCP server can be installed with `knowhow`
- Zenodo concept DOI in `CITATION.cff` and a README badge

### CI

- Publish to PyPI automatically when a GitHub release is published
- Validate skills with `knowhow` on push and pull requests

## [2.2.2] - 2026-10-20

### Added

- CLI options for non-interactive mode and download limits
- Warn the user when the embedding configuration has changed
- Verbose output and better affiliation assignment for NSF COA generation
- `CITATION.cff`

### Fixed

- Adapted to OpenAlex API breaking changes, added missing work types, and replaced the deprecated `host_venue` with `primary_location`
- Authors with missing OpenAlex IDs no longer break COA generation; duplicate COA profiles resolved
- torch compatibility issues
- Suppressed verbose `sentence_transformers` output
- Removed the `playsound` dependency in favor of platform-native audio playback
- Pinned `bibtexparser<2` (litdb uses the 1.x API) and `pymupdf4llm<2` (the 2.0 PyPI release was an empty wheel)
- Read the litdb version with `importlib.metadata`; `pkg_resources` is gone on Python 3.12+

### CI

- Lint with the ruff version locked in `uv.lock` instead of the latest release

## [2.2.1] - 2025-10-31

### Fixed

- Read-only file system error in the MCP server's NSF COA generation

## [2.2.0] - 2025-10-30

### Added

- `litdb install` commands for the Claude Code skill and the MCP server
- NSF COA generator tab in the Streamlit app, with ORCID input
- NSF COA generation tool in the MCP server

### Fixed

- Citations are generated from OpenAlex metadata with full author lists
- `mcp-server` install uses the current config database
- MCP tools return concise summaries and full abstracts, avoiding token-limit errors
- Lazy loading for article display in the Manage Filters tab

## [2.1.9] - 2025-10-26

### Added

- Optional dependency groups (`research`, `app`, `youtube`, `crawl`, `image`, `mcp`, `audio`, `futurehouse`, `all`)
- Interactive research and file/directory upload in the Streamlit app
- Filter descriptions in the Manage Filters tab, and the version in the app sidebar

### Refactored

- **CLI Architecture**: Completed major refactoring of CLI codebase
  - Reduced `cli.py` from 932 lines to 128 lines (86% reduction)
  - Extracted 43 commands into 10 focused modules in `src/litdb/commands/`:
    - `manage.py` - Core database management (6 commands: init, add, remove, index, reindex, update_embeddings)
    - `search.py` - Search functionality (7 commands: vsearch, fulltext, hybrid_search, lsearch, similar, image_search, screenshot)
    - `export.py` - Export and display (6 commands: bibtex, citation, show, visit, about, sql)
    - `tags.py` - Tag management (5 commands: add_tag, rm_tag, delete_tag, show_tag, list_tags)
    - `review.py` - Review and summary (2 commands: review, summary)
    - `filters.py` - Filter management (4 commands: add_filter, rm_filter, update_filters, list_filters)
    - `openalex_commands.py` - OpenAlex integration (7 commands: openalex, author_search, follow, watch, citing, related, unpaywall)
    - `research_commands.py` - Research tools (3 commands: fhresearch, research, suggest_reviewers)
    - `data_processing.py` - Data processing (5 commands: crossref, fromtext, extract, schema, crawl)
    - `utilities.py` - Utility commands (6 commands: web, audio, chat, app, version, coa)
  - `cli.py` now serves only as a clean orchestration layer
  - All existing functionality preserved, no breaking changes
  - Improved code organization and maintainability

### Fixed

- Optional-dependency imports are lazy, so the core install works without the extras
- Updated langchain imports for the split package structure
- Removed `playsound`, which is incompatible with Python 3.12+
- Updated the FutureHouse client API and show full citations in search
- Copy buttons now display in Streamlit search results
- **Tests**: Fixed failing CI tests in `test_cli_openalex.py`
  - Fixed `test_unpaywall_basic` - Added missing mock response fields
  - Fixed `test_follow_remove` - Added proper mocks for `add_author()` and `get_openalex_db()`
  - All 133 tests now passing (66 skipped integration tests)
  - CI/CD pipeline green on main branch

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
