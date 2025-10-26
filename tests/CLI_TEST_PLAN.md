# CLI Testing Plan Before Refactoring

## Goal
Achieve 25-30% coverage of cli.py (currently 0%) before refactoring into modules.
This ensures we can safely restructure without breaking functionality.

## Strategy
Test commands in order of:
1. **Critical path** - core functionality
2. **Complexity** - commands with complex logic
3. **Refactoring impact** - commands moving to different modules
4. **New features** - recently added features

## Commands by Priority

### Phase 1: Core Setup & Database Operations (CRITICAL)
**Target Module:** `commands/manage.py` and `commands/add.py`

- [ ] `init` - Initialize litdb project
  - Test creates litdb.toml
  - Test creates database
  - Test prompts for config

- [ ] `add` - Add sources to database
  - Test adding by DOI
  - Test adding by ORCID
  - Test adding from bibtex file
  - Test with --references, --citing, --related flags
  - Test error handling (invalid DOI, network errors)

- [ ] `remove` - Remove sources
  - Test removing by source
  - Test confirmation prompt

### Phase 2: Search Commands (HIGH PRIORITY)
**Target Module:** `commands/search.py`

- [ ] `vsearch` - Vector search (core feature)
  - Test basic search
  - Test with -n limit
  - Test with --cross-encode
  - Test with different output formats (-f)

- [ ] `fulltext` - Full-text search
  - Test basic search
  - Test with SQL-like syntax

- [ ] `hybrid-search` - Combined search
  - Test hybrid functionality

- [ ] `lsearch` - LLM-enhanced search
  - Mock LLM calls
  - Test query generation

### Phase 3: New Features (HIGH PRIORITY - Recently Added)
**Target Modules:** `commands/review.py`, `commands/extract.py`

- [ ] `summary` - Newsletter generation
  - Test with different time periods (-s)
  - Test output file creation (-o)
  - Test with custom model (--model)
  - Mock LLM calls
  - Mock database queries

- [ ] `fromtext` - Extract references from text
  - Test with DOI in text
  - Test with multiple references
  - Test with --references, --related, --citing
  - Mock CrossRef API
  - Mock LLM calls

- [ ] `extract` - Extract tables from PDF
  - Test with PDF file (fixture)
  - Test with -t to select tables
  - Test output formats (-f)

- [ ] `schema` - Extract structured data
  - Test with DSL schema
  - Test with JSON schema
  - Mock LLM calls

### Phase 4: Export Commands (MEDIUM PRIORITY)
**Target Module:** `commands/export.py`

- [ ] `bibtex` - Generate bibtex entries
  - Test basic export
  - Test filtering

- [ ] `citation` - Generate citation strings
  - Test different citation formats

- [ ] `review` - Review recent additions
  - Test with different time periods
  - Test output formatting

### Phase 5: Filter & Tag Management (MEDIUM PRIORITY)
**Target Module:** `commands/manage.py`

- [ ] `add-filter` - Add OpenAlex filter
  - Test filter creation
  - Test validation

- [ ] `list-filters` - List filters
  - Test output

- [ ] `rm-filter` - Remove filter
  - Test removal

- [ ] `add-tag` - Tag sources
  - Test adding tags

- [ ] `list-tags` - List tags
  - Test output

- [ ] `rm-tag` - Remove tags
  - Test tag removal

- [ ] `delete-tag` - Delete tag completely
  - Test deletion

### Phase 6: Less Critical (LOWER PRIORITY)
**Various modules**

- [ ] `about` - Statistics
- [ ] `open` - Open source
- [ ] `show` - Display source
- [ ] `openalex` - OpenAlex queries
- [ ] `author-search` - Search for authors
- [ ] `crossref` - CrossRef queries
- [ ] `chat` - Chat interface
- [ ] `gpt` - GPT interface
- [ ] `research` - Deep research
- [ ] `app` - Streamlit app launch
- [ ] `crawl` - Web crawling
- [ ] `index` / `reindex` - File indexing
- [ ] `audio` - Audio recording
- [ ] `screenshot` - Screenshot search
- [ ] `image-search` - Image search

## Testing Approach

### Tools
- `click.testing.CliRunner` - Invoke commands programmatically
- `pytest-mock` - Mock external dependencies
- `responses` - Mock HTTP API calls
- Temporary databases for isolation

### Mock Strategy
1. **Mock external APIs:**
   - OpenAlex API calls
   - CrossRef API calls
   - LLM calls (litellm)

2. **Use temp databases:**
   - Create fresh database for each test
   - Populate with known data
   - Verify changes

3. **Mock file system:**
   - Use temp directories
   - Provide PDF fixtures for extract/schema tests

### Coverage Target by Phase

- **Phase 1 (Core):** +10% coverage
- **Phase 2 (Search):** +8% coverage
- **Phase 3 (New Features):** +7% coverage
- **Phase 4 (Export):** +3% coverage
- **Total:** ~28% coverage

## Example Test Structure

```python
from click.testing import CliRunner
from litdb.cli import cli
import pytest

class TestAddCommand:
    """Test the 'add' command."""

    def test_add_doi_basic(self, test_db, mock_openalex):
        """Test adding a work by DOI."""
        runner = CliRunner()
        result = runner.invoke(cli, ['add', 'https://doi.org/10.1234'])

        assert result.exit_code == 0
        assert "Added" in result.output
        # Verify it's in database

    def test_add_invalid_doi(self):
        """Test error handling for invalid DOI."""
        runner = CliRunner()
        result = runner.invoke(cli, ['add', 'invalid'])

        assert result.exit_code != 0
        assert "Error" in result.output
```

## Success Criteria

1. ✅ All Phase 1-3 commands have tests
2. ✅ cli.py coverage reaches 25-30%
3. ✅ All tests pass consistently
4. ✅ CI/CD runs CLI tests on every commit
5. ✅ Refactoring can proceed with confidence

## Timeline

- **Phase 1:** 2-3 hours
- **Phase 2:** 2-3 hours
- **Phase 3:** 3-4 hours
- **Phase 4:** 1-2 hours
- **Total:** 8-12 hours of focused work

## After Testing Complete

Once we have good coverage:
1. Refactor cli.py into modules
2. Tests will catch any regressions
3. Coverage should remain stable or increase
4. Code will be more maintainable
