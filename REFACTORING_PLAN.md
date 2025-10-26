# CLI Refactoring Plan

## Goal
Split cli.py (932 lines, ~48 commands) into focused modules with test coverage.

## Strategy
Refactor in phases, adding tests before each refactoring step.

---

## Phase 1: Core Management (commands/manage.py)
**Priority:** HIGH - Foundation commands, `init` already tested

### Commands to Move:
- `init` - Initialize litdb project ✅ **3 tests passing**
- `add` - Add sources to database
- `remove` - Remove sources
- `index` - Index files
- `reindex` - Reindex saved directories
- `update_embeddings` - Update embeddings

### Test Coverage Needed:
- [ ] `add` - Test adding by DOI, ORCID, bibtex (mock APIs)
- [ ] `remove` - Test removal with confirmation
- [ ] `index` - Test file indexing
- [ ] `reindex` - Test reindexing
- [ ] `update_embeddings` - Test embedding updates

### Estimated Test Time: 2-3 hours

---

## Phase 2: Search Commands (commands/search.py)
**Priority:** HIGH - Core functionality

### Commands to Move:
- `vsearch` - Vector search (most important)
- `fulltext` - Full-text search
- `hybrid_search` - Combined search
- `lsearch` - LLM-enhanced search
- `similar` - Similar sources
- `image_search` - Image search
- `screenshot` - Screenshot search

### Test Coverage Needed:
- [ ] `vsearch` - Basic search, with limits, cross-encode (mock embeddings)
- [ ] `fulltext` - Basic FTS5 search
- [ ] `hybrid_search` - Combined search
- [ ] Others - Basic existence tests

### Estimated Test Time: 2-3 hours

---

## Phase 3: Export & Display (commands/export.py)
**Priority:** MEDIUM - Frequently used

### Commands to Move:
- `bibtex` - Generate bibtex
- `citation` - Generate citations
- `show` - Display source details
- `visit` (open) - Open source
- `about` - Database statistics ✅ **1 test (skipped)**
- `sql` - Run SQL queries

### Test Coverage Needed:
- [ ] `bibtex` - Test bibtex generation
- [ ] `citation` - Test citation formatting
- [ ] `show` - Test display
- [ ] `about` - Unskip and enhance existing test

### Estimated Test Time: 1-2 hours

---

## Phase 4: Tags (commands/tags.py)
**Priority:** MEDIUM - Self-contained

### Commands to Move:
- `add_tag` - Add tags to sources
- `rm_tag` - Remove tags
- `delete_tag` - Delete tag entirely
- `show_tag` - Show tagged sources
- `list_tags` - List all tags

### Test Coverage Needed:
- [ ] Tag CRUD operations
- [ ] Tag-source associations

### Estimated Test Time: 1-2 hours

---

## Phase 5: Review & Summary (commands/review.py)
**Priority:** MEDIUM - New features

### Commands to Move:
- `review` - Review recent additions
- `summary` - Newsletter generation ✅ **Tests exist (skipped)**

### Test Coverage Needed:
- [ ] Unskip existing summary tests
- [ ] Add review tests

### Estimated Test Time: 1 hour

---

## Phase 6: Extraction (commands/extract.py)
**Priority:** MEDIUM - New features

### Commands to Move:
- `fromtext` - Extract references from text ✅ **1 test passing**
- `extract` - Extract tables from PDF ✅ **1 test passing**
- `schema` - Extract structured data ✅ **1 test passing**

### Test Coverage Needed:
- [ ] Unskip existing integration tests
- [ ] Add mocked versions

### Estimated Test Time: 1-2 hours

---

## Phase 7-12: Lower Priority
- Filters (add_filter, rm_filter, etc.)
- Watching (follow, watch, citing, related)
- External APIs (crossref, openalex, etc.)
- Research (research, fhresearch, crawl)
- Chat (chat_command, gpt, audio)
- Misc (coa, suggest_reviewers, version)

---

## Proposed Execution Order

### Sprint 1: Foundation (Phase 1)
1. Add tests for `add`, `remove`, `index` commands
2. Create `commands/manage.py`
3. Move commands with tests passing
4. Update imports in `cli.py`
5. Verify all tests still pass

### Sprint 2: Search (Phase 2)
1. Add tests for `vsearch`, `fulltext`
2. Create `commands/search.py`
3. Move search commands
4. Update imports
5. Verify tests pass

### Sprint 3: Export & Display (Phase 3)
1. Add tests for export commands
2. Create `commands/export.py`
3. Move commands
4. Update imports

### Sprint 4+: Continue with remaining phases

---

## Success Criteria Per Sprint
- ✅ All new tests pass
- ✅ All existing tests still pass
- ✅ Coverage doesn't decrease
- ✅ CLI commands work identically
- ✅ No import errors

---

## Current Status
- **Total CLI coverage:** 23.74%
- **Passing tests:** 7
- **Skipped tests:** 45
- **Ready to start:** Phase 1 (manage.py)
