# litdb Tests

This directory contains the test suite for litdb.

## Quick Start

```bash
# Install test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with coverage
pytest --cov=src/litdb --cov-report=html
open htmlcov/index.html
```

## Directory Structure

```
tests/
├── README.md             # This file
├── conftest.py           # Shared pytest fixtures
├── unit/                 # Fast unit tests (no external dependencies)
│   ├── test_extract.py   # Schema DSL parser tests
│   ├── test_summary.py   # JSON parsing and summary tests
│   ├── test_utils.py     # Utility function tests
│   └── test_openalex_api.py  # API parameter tests
├── integration/          # Integration tests (may use external services)
└── fixtures/             # Test data and fixtures
```

## Test Coverage

Current coverage: **~9%** (initial tests for critical security-sensitive code)

**Covered modules:**
- ✅ `extract.py` (59% - security-critical schema parser)
- ✅ `summary.py` (19% - robust JSON parser)
- ✅ `utils.py` (65% - configuration loading)
- 🟡 `openalex.py` (32% - API parameter tests)

**Needs coverage:**
- ⏳ `cli.py` (0% - 928 lines, needs command tests)
- ⏳ `db.py` (17% - needs database operation tests)
- ⏳ `chat.py` (17% - needs LLM mocking)

## Running Tests

See [TESTING.md](../TESTING.md) for detailed instructions on:
- Running specific tests
- Using test markers
- Generating coverage reports
- Writing new tests
- CI/CD integration

## Test Philosophy

1. **Security-critical code** gets tested first (extract.py, db.py)
2. **Complex logic** gets comprehensive tests (summary.py, JSON parsing)
3. **Regression tests** for all bug fixes (mailto parameter, eval() vulnerability)
4. **Integration tests** are clearly marked and skippable
5. **Fast unit tests** run on every commit

## Contributing Tests

When adding new code:
1. Write tests for new features
2. Write regression tests for bug fixes
3. Aim for >80% coverage on critical modules
4. Use fixtures from conftest.py
5. Mark integration tests with `@pytest.mark.integration`

## Current Test Stats

- **Total tests:** 45 (36 passed, 9 skipped)
- **Unit tests:** 36 passing
- **Integration tests:** 9 skipped (need fixtures/mocking)
- **Test execution time:** ~7 seconds

## Next Steps

High priority tests to add:
1. Database operations (add_source, vector search)
2. CLI command tests (using click.testing)
3. OpenAlex API mocking
4. LLM response mocking for summary tests
5. PDF processing with test fixtures
