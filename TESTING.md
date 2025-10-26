# Testing Guide for litdb

This document describes how to run tests for litdb.

## Quick Start

```bash
# Install litdb with test dependencies
pip install -e ".[test]"

# Run all tests
pytest

# Run with coverage
pytest --cov=src/litdb --cov-report=html

# Open coverage report in browser
open htmlcov/index.html
```

## Test Structure

```
tests/
├── conftest.py           # Shared fixtures and configuration
├── unit/                 # Unit tests (fast, no external dependencies)
│   ├── test_extract.py   # Schema DSL parser tests
│   ├── test_summary.py   # JSON parsing tests
│   ├── test_utils.py     # Utility function tests
│   └── test_openalex_api.py  # API parameter tests
├── integration/          # Integration tests (may call external APIs)
└── fixtures/             # Test fixtures and sample data
```

## Running Tests

### Run All Tests

```bash
pytest
```

### Run Specific Test Files

```bash
# Run only unit tests
pytest tests/unit

# Run specific test file
pytest tests/unit/test_extract.py

# Run specific test class
pytest tests/unit/test_extract.py::TestParseSchemaDSL

# Run specific test
pytest tests/unit/test_extract.py::TestParseSchemaDSL::test_simple_schema
```

### Run Tests by Marker

```bash
# Run only unit tests (fast)
pytest -m unit

# Run only integration tests
pytest -m integration

# Skip slow tests
pytest -m "not slow"
```

### Verbose Output

```bash
# Show test names and results
pytest -v

# Show print statements
pytest -s

# Show local variables on failure
pytest -l
```

## Coverage

### Generate Coverage Reports

```bash
# Terminal report with missing lines
pytest --cov=src/litdb --cov-report=term-missing

# HTML report (most detailed)
pytest --cov=src/litdb --cov-report=html
open htmlcov/index.html

# XML report (for CI/CD)
pytest --cov=src/litdb --cov-report=xml
```

### Coverage Goals

- **Overall:** Aim for >80% coverage
- **Critical modules:** >90% coverage
  - `extract.py` (security-critical)
  - `db.py` (data integrity)
  - `summary.py` (complex logic)

### View Coverage

```bash
# Simple terminal report
coverage report

# Detailed HTML report
coverage html
open htmlcov/index.html
```

## Test Categories

### Unit Tests

Fast tests with no external dependencies. Mock all I/O operations.

**Characteristics:**
- No network calls
- No file system access (use temp directories)
- No database access (use in-memory databases)
- Should run in milliseconds

**Run with:**
```bash
pytest -m unit
```

### Integration Tests

Tests that interact with external systems.

**Characteristics:**
- May call OpenAlex API (rate-limited)
- May access file system
- May use test databases
- Slower (seconds to minutes)

**Run with:**
```bash
pytest -m integration
```

### Slow Tests

Long-running tests (e.g., LLM calls, large dataset processing).

**Run with:**
```bash
pytest -m slow
```

## Writing Tests

### Test Naming

```python
# File names
test_<module>.py

# Test classes
class Test<Feature>:

# Test functions
def test_<what_it_tests>():
def test_<scenario>_<expected_result>():
```

### Using Fixtures

```python
def test_with_config(mock_config):
    """Use the mock_config fixture from conftest.py"""
    assert "embedding" in mock_config

def test_with_temp_dir(temp_dir):
    """Use temp_dir fixture for file operations"""
    test_file = temp_dir / "test.txt"
    test_file.write_text("content")
```

### Markers

```python
import pytest

@pytest.mark.unit
def test_fast_operation():
    """Fast unit test"""
    pass

@pytest.mark.integration
def test_api_call():
    """Integration test that calls external API"""
    pass

@pytest.mark.slow
def test_large_dataset():
    """Slow test processing large data"""
    pass
```

### Parametrize Tests

```python
@pytest.mark.parametrize("input,expected", [
    ("simple", "result"),
    ("complex", "other_result"),
])
def test_multiple_cases(input, expected):
    assert process(input) == expected
```

## Continuous Integration

Tests run automatically on GitHub Actions for:
- Every push to `main` and `develop` branches
- Every pull request

### CI Configuration

See `.github/workflows/test.yml` for the CI configuration.

**Test Matrix:**
- Python versions: 3.10, 3.11, 3.12, 3.13
- Operating System: Ubuntu latest

### CI Reports

- Coverage reports are uploaded to Codecov
- Test results appear in PR checks
- Linting runs separately (ruff)

## Troubleshooting

### Tests Fail Locally But Pass in CI

- Check Python version: `python --version`
- Ensure test dependencies are installed: `pip install -e ".[test]"`
- Clear pytest cache: `pytest --cache-clear`

### ImportError in Tests

```bash
# Install package in editable mode
pip install -e .

# Or with test dependencies
pip install -e ".[test]"
```

### Coverage Not Showing Changes

```bash
# Clear coverage data
coverage erase

# Re-run tests
pytest --cov=src/litdb
```

### Slow Tests

```bash
# Show slowest 10 tests
pytest --durations=10

# Skip slow tests
pytest -m "not slow"
```

## Best Practices

### DO

- ✅ Write tests for new features
- ✅ Write tests for bug fixes (regression tests)
- ✅ Use descriptive test names
- ✅ Keep tests focused (one concept per test)
- ✅ Use fixtures for common setup
- ✅ Mock external dependencies
- ✅ Test edge cases and error conditions

### DON'T

- ❌ Test implementation details
- ❌ Make tests depend on each other
- ❌ Use real API keys in tests
- ❌ Commit test databases or large fixtures
- ❌ Skip tests without a good reason
- ❌ Write tests that are flaky (random failures)

## Test Coverage by Module

Current status (run `pytest --cov` to update):

- `extract.py`: ✅ Covered (security-critical)
- `summary.py`: ✅ Covered (JSON parsing)
- `utils.py`: 🟡 Partial coverage
- `db.py`: ⏳ Needs more tests
- `cli.py`: ⏳ Needs more tests
- `openalex.py`: 🟡 API parameter tests only

Legend:
- ✅ Good coverage (>80%)
- 🟡 Partial coverage (50-80%)
- ⏳ Needs tests (<50%)

## Future Test Improvements

### High Priority

- [ ] Add database integration tests
- [ ] Add CLI command tests (click.testing)
- [ ] Mock OpenAlex API responses
- [ ] Add PDF processing tests with fixtures

### Medium Priority

- [ ] Add LLM mocking for summary tests
- [ ] Add vector search tests
- [ ] Test error handling paths
- [ ] Add performance benchmarks

### Low Priority

- [ ] Property-based testing (Hypothesis)
- [ ] Mutation testing
- [ ] Test documentation (doctest)

## Resources

- [pytest documentation](https://docs.pytest.org/)
- [pytest-cov documentation](https://pytest-cov.readthedocs.io/)
- [pytest-mock documentation](https://pytest-mock.readthedocs.io/)
- [Coverage.py documentation](https://coverage.readthedocs.io/)

## Getting Help

If tests are failing or you need help writing tests:

1. Check this document first
2. Look at existing tests for examples
3. Run with `-v` and `-s` for more output
4. Check GitHub Actions logs for CI failures
5. Open an issue on GitHub
