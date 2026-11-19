"""Streamlit app for litdb.

Enhanced multi-tab interface for literature database management.
"""

import html
import json
import logging
import os
import warnings

import numpy as np
import pandas as pd
import streamlit as st
from litellm import completion

from litdb.bibtex import dump_bibtex
from litdb.chat import get_rag_content
from litdb.db import add_work as _db_add_work
from litdb.db import get_db, get_model
from litdb.openalex import abstract_text
from litdb.utils import fts_query, get_config

# Suppress torch-related errors from Streamlit's file watcher
warnings.filterwarnings("ignore", category=RuntimeWarning, module="streamlit")
logging.getLogger("streamlit.watcher.local_sources_watcher").setLevel(logging.ERROR)

# Configuration
config = get_config()
db = get_db()
gpt = config.get("llm", {"model": "ollama/llama2"})
dbf = os.path.join(config["root"], "litdb.libsql")

# Constants
KB = 1024
MB = 1024 * KB
GB = 1024 * MB


def add_work(source, **kwargs):
    """Add the work SOURCE (a DOI or OpenAlex id) and return its key.

    The app has no terminal, so add_work must never prompt (yes=True), and a
    work OpenAlex does not know is an error instead of a silent success.
    """
    source = source.strip()
    if source.startswith("10."):
        source = f"https://doi.org/{source}"
    key = _db_add_work(source, yes=True, **kwargs)
    if key is None:
        raise ValueError(f"{source} was not found in OpenAlex.")
    return key


def vector_search(query, n):
    """Return (source, text, extra, distance) rows nearest to QUERY."""
    model = get_model(config["embedding"]["model"])
    emb = model.encode([query]).astype(np.float32).tobytes()
    return db.execute(
        """SELECT sources.source, sources.text, sources.extra,
           vector_distance_cos(?, embedding) as d
           FROM vector_top_k('embedding_idx', ?, ?)
           JOIN sources ON sources.rowid = id
           ORDER BY d""",
        [emb, emb, n],
    ).fetchall()


# Snippet markers. The matched text is escaped before they become <b> tags,
# since the snippet is rendered as HTML.
SNIPPET_START, SNIPPET_END = "\x02", "\x03"


def fulltext_search(sql, query, n):
    """Run the full-text SQL for QUERY, showing an error if it is invalid."""
    try:
        return fts_query(db, sql, query, n)
    except ValueError as e:
        st.error(f"Invalid full-text query: {e}")
        return []


def snippet_html(snippet):
    """Return SNIPPET as HTML with the matched words in bold."""
    return (
        html.escape(snippet or "")
        .replace(SNIPPET_START, "<b>")
        .replace(SNIPPET_END, "</b>")
    )


def preview(text, n):
    """Return the first N characters of TEXT (which may be None)."""
    text = text or ""
    return text[:n] + "..." if len(text) > n else text


def author_names(work, limit=3):
    """Return up to LIMIT author names of the OpenAlex WORK."""
    authorships = work.get("authorships") or []
    names = [
        (a.get("author") or {}).get("display_name") or "Unknown"
        for a in authorships[:limit]
    ]
    if len(authorships) > limit:
        names.append("et al.")
    return names


def work_buttons(source, key, add_paper=False):
    """Show buttons that add SOURCE's references, citing and related works.

    With ADD_PAPER, also a button that adds SOURCE itself.
    """
    actions = [
        ("📚 Add References", "references", "References added"),
        ("📝 Add Citing", "citing", "Citing papers added"),
        ("🔗 Add Related", "related", "Related works added"),
    ]
    if add_paper:
        actions.insert(0, ("➕ Add to Library", None, "Paper added to library"))
    for col, (label, what, done) in zip(st.columns(len(actions)), actions):
        with col:
            if st.button(label, key=f"{what or 'add'}_{key}"):
                with st.spinner("Adding..."):
                    try:
                        add_work(source, **({what: True} if what else {}))
                        st.success(f"✓ {done}!")
                    except Exception as e:
                        st.error(f"Error: {e}")


def tag_editor(source, key):
    """Show the tags of SOURCE with buttons to remove them or add one."""
    st.markdown("**🏷️ Tags:**")
    current_tags = get_tags_for_source(source)
    if current_tags:
        cols = st.columns(len(current_tags) + 1)
        for idx, tag in enumerate(current_tags):
            with cols[idx]:
                if st.button(
                    f"🗑️ {tag}", key=f"rm_tag_{key}_{tag}"
                ) and remove_tag_from_source(source, tag):
                    st.success(f"Removed tag: {tag}")
                    st.rerun()
    else:
        st.caption("No tags yet")

    new_tag_col1, new_tag_col2 = st.columns([3, 1])
    with new_tag_col1:
        new_tag = st.text_input(
            "Add tag",
            key=f"new_tag_{key}",
            placeholder="Enter tag name...",
            label_visibility="collapsed",
        )
    with new_tag_col2:
        if st.button("➕ Add", key=f"add_tag_{key}") and new_tag and new_tag.strip():
            if add_tag_to_source(source, new_tag.strip()):
                st.success(f"Added tag: {new_tag}")
                st.rerun()
            else:
                st.warning("Tag already exists")


def get_db_stats():
    """Get database statistics."""
    (nsources,) = db.execute("select count(source) from sources").fetchone()
    db_size = os.path.getsize(dbf) / GB
    return nsources, db_size


def render_sidebar():
    """Render sidebar with navigation and database info."""
    st.sidebar.title("LitDB")

    # Show version
    try:
        from importlib.metadata import version

        litdb_version = version("litdb")
        st.sidebar.caption(f"Version {litdb_version}")
    except Exception:
        st.sidebar.caption("Version unknown")

    st.sidebar.markdown("---")

    # GitHub links
    st.sidebar.markdown("""
    **Links**
    - [GitHub Repository](https://github.com/jkitchin/litdb)
    - [Report Issues](https://github.com/jkitchin/litdb/issues)
    """)

    st.sidebar.markdown("---")

    # Database stats in sidebar
    nsources, db_size = get_db_stats()
    st.sidebar.markdown(f"""
    **Database Info**
    - Sources: {nsources}
    - Size: {db_size:.2f} GB
    """)

    st.sidebar.markdown("---")

    # Tab selection
    tab = st.sidebar.radio(
        "Navigation",
        [
            "🔍 Search",
            "🔎 OpenAlex Search",
            "📖 Semantic Scholar Search",
            "👥 Suggest Reviewers",
            "💬 Chat",
            "📚 Library Browser",
            "⚙️ Manage Filters",
            "📈 Stats & Analytics",
            "📤 Export",
            "🔬 Research",
            "➕ Add Content",
            "📋 NSF COA",
        ],
    )

    return tab


def get_tags_for_source(source):
    """Get all tags for a source."""
    try:
        source_id_result = db.execute(
            "SELECT rowid FROM sources WHERE source = ?", (source,)
        ).fetchone()

        if not source_id_result:
            return []

        (source_id,) = source_id_result
        tags = db.execute(
            """SELECT tags.tag FROM tags
               INNER JOIN source_tag ON source_tag.tag_id = tags.rowid
               WHERE source_tag.source_id = ?""",
            (source_id,),
        ).fetchall()
        return [tag[0] for tag in tags]
    except Exception:
        return []


def add_tag_to_source(source, tag):
    """Add a tag to a source."""
    try:
        # Get source id
        (source_id,) = db.execute(
            "SELECT rowid FROM sources WHERE source = ?", (source,)
        ).fetchone()

        # Get or create tag
        tag_result = db.execute(
            "SELECT rowid FROM tags WHERE tag = ?", (tag,)
        ).fetchone()

        if not tag_result:
            cursor = db.execute("INSERT INTO tags(tag) VALUES (?)", (tag,))
            tag_id = cursor.lastrowid
            db.commit()
        else:
            (tag_id,) = tag_result

        # Check if tag already exists for this source
        existing = db.execute(
            "SELECT rowid FROM source_tag WHERE source_id = ? AND tag_id = ?",
            (source_id, tag_id),
        ).fetchone()

        if not existing:
            db.execute(
                "INSERT INTO source_tag(source_id, tag_id) VALUES (?, ?)",
                (source_id, tag_id),
            )
            db.commit()
            return True
        return False
    except Exception as e:
        st.error(f"Error adding tag: {e}")
        return False


def remove_tag_from_source(source, tag):
    """Remove a tag from a source."""
    try:
        # Get source id and tag id
        (source_id,) = db.execute(
            "SELECT rowid FROM sources WHERE source = ?", (source,)
        ).fetchone()
        (tag_id,) = db.execute(
            "SELECT rowid FROM tags WHERE tag = ?", (tag,)
        ).fetchone()

        db.execute(
            "DELETE FROM source_tag WHERE source_id = ? AND tag_id = ?",
            (source_id, tag_id),
        )
        db.commit()
        return True
    except Exception as e:
        st.error(f"Error removing tag: {e}")
        return False


def format_citation(extra):
    """Format citation from extra JSON data."""
    if not extra:
        return None

    try:
        data = json.loads(extra)

        # Try to build a citation
        parts = []

        # Authors
        if authors := author_names(data):
            parts.append(", ".join(authors))

        # Year
        if data.get("publication_year"):
            parts.append(f"({data['publication_year']})")

        # Title
        if data.get("title"):
            parts.append(data["title"])

        # Journal/venue
        pl = data.get("primary_location") or {}
        src = pl.get("source") or {}
        venue = src.get("display_name", "")
        if venue:
            parts.append(f"*{venue}*")

        return ". ".join(parts) if parts else None
    except Exception:
        return None


def tab_search():
    """Search tab with vector, full-text, and hybrid search."""
    st.title("🔍 Search")

    # Custom CSS for larger, more readable text
    st.markdown(
        """
    <style>
    /* Increase base font size in expanders and markdown */
    .stMarkdown p {
        font-size: 18px !important;
        line-height: 1.6;
    }

    /* Larger expander titles */
    .streamlit-expanderHeader {
        font-size: 18px !important;
    }

    /* Larger text in expander content */
    .streamlit-expanderContent {
        font-size: 17px !important;
    }

    /* Code blocks (BibTeX, citations) */
    code {
        font-size: 15px !important;
    }

    /* Headers within results */
    .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
        font-size: 20px !important;
    }

    /* Strong/bold text */
    .stMarkdown strong {
        font-size: 18px !important;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # Use form to allow Enter key to submit
    with st.form("search_form"):
        search_type = st.selectbox(
            "Search Type", ["Vector Search", "Full-Text Search", "Hybrid Search"]
        )
        query = st.text_input("Enter your search query")
        n_results = st.slider("Number of results", 1, 20, 5)
        search_submitted = st.form_submit_button("Search")

    # Store search parameters in session state
    if search_submitted:
        if not query:
            st.warning("Please enter a search query")
            return

        st.session_state.last_search_query = query
        st.session_state.last_search_type = search_type
        st.session_state.last_n_results = n_results

    # Check for iteration button click BEFORE determining should_search
    # This handles the case where button triggers iteration -> rerun -> search
    iteration_requested = st.session_state.get("run_iteration", False)

    if iteration_requested:
        st.session_state.run_iteration = False  # Clear the flag

        # Process the iteration

        last_results = st.session_state.get("last_search_results", [])

        if last_results:
            # Show progress
            progress_bar = st.progress(0)
            status_text = st.empty()

            # Collect DOIs from last results
            dois_to_process = []
            for result in last_results:
                source, text, extra = result[0], result[1], result[2]
                if extra:
                    try:
                        extra_data = json.loads(extra)
                        doi = extra_data.get("doi") or extra_data.get("id")
                        if doi and (doi.startswith(("http", "10."))):
                            dois_to_process.append(doi)
                    except Exception:
                        pass

            processed = 0
            total = len(dois_to_process)

            # Create a container for detailed status
            status_container = st.container()

            for idx, doi in enumerate(dois_to_process, 1):
                with status_container:
                    status_text.markdown(f"""
**Processing paper {idx}/{total}**
DOI: `{doi}`
Adding: references, citations, and related works...
                    """)
                try:
                    add_work(doi, references=True, citing=True, related=True)
                    processed += 1
                    with status_container:
                        st.success(f"✓ Completed paper {idx}/{total}")
                except Exception as e:
                    with status_container:
                        st.error(f"✗ Could not process {doi}: {e}")

                progress_bar.progress(idx / total)

            if processed > 0:
                # Store iteration status for display
                st.session_state.iteration_status = {
                    "processed": processed,
                    "total": total,
                }

                status_text.text(
                    f"✓ Completed! Processed {processed}/{total} papers. "
                    f"Refreshing search results..."
                )

                # Set flag to rerun search
                st.session_state.rerun_search = True

                # Small delay to show completion
                import time

                time.sleep(0.5)

                # Clear progress indicators before rerun
                progress_bar.empty()
                status_text.empty()

                # Trigger rerun to execute the search with new data
                st.rerun()
            else:
                progress_bar.empty()
                status_text.empty()
                st.warning("No papers could be processed for iteration.")

    # Check if we should run a search (either from form or after iteration)
    # Also show search results if we have previous search parameters (so button stays visible)
    has_previous_search = "last_search_query" in st.session_state
    should_search = (
        search_submitted
        or st.session_state.get("rerun_search", False)
        or has_previous_search
    )

    if should_search:
        # Determine if we need to actually run a query or just show previous results
        should_run_query = search_submitted or st.session_state.get(
            "rerun_search", False
        )

        # Clear the rerun flag if it was set
        if st.session_state.get("rerun_search", False):
            st.session_state.rerun_search = False

        # Use stored parameters if available
        query = st.session_state.get("last_search_query", query)
        search_type = st.session_state.get("last_search_type", search_type)
        n_results = st.session_state.get("last_n_results", n_results)

        st.subheader("Results")

        # Display iteration status banner if available
        if "iteration_status" in st.session_state:
            status = st.session_state.iteration_status
            st.success(
                f"✓ Iteration completed: Added references, citations, and related works for "
                f"{status['processed']} of {status['total']} papers. "
                f"Results updated below."
            )
            # Clear the status after displaying
            del st.session_state.iteration_status

        # ===== DISPLAY RESULTS (from fresh query or cache) =====
        if search_type == "Vector Search":
            # Execute query if needed
            if should_run_query:
                # Vector search - we need to compute embedding first
                results = vector_search(query, n_results)

                # Store results in session state
                st.session_state.last_search_results = results
            else:
                # Use cached results
                results = st.session_state.get("last_search_results", [])
                if not results:
                    st.warning("No cached results available")

            # Display results
            for i, (source, text, extra, distance) in enumerate(results, 1):
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title} (distance: {distance:.4f})"):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Text preview:** {preview(text, 300)}")

                    # Add copy buttons for citation and BibTeX
                    if extra:
                        try:
                            extra_data = json.loads(extra)

                            # Citation copy button
                            if citation:
                                st.markdown("---")
                                st.markdown("**📋 Copy Citation:**")
                                st.code(citation, language="text")

                            # BibTeX copy button
                            from litdb.bibtex import dump_bibtex

                            bibtex = dump_bibtex(extra_data)
                            if bibtex:
                                st.markdown("**📋 Copy BibTeX:**")
                                st.code(bibtex, language="bibtex")
                        except Exception as e:
                            st.error(
                                f"Error generating copy buttons: {e}"
                            )  # Show error for debugging
                    else:
                        st.warning("No metadata available for copy buttons")

                    # Tags section
                    st.markdown("---")
                    tag_editor(source, f"v_{i}")

                    # Check if this is a DOI/OpenAlex entry to show add buttons
                    doi = None
                    if extra:
                        try:
                            extra_data = json.loads(extra)
                            doi = extra_data.get("doi") or extra_data.get("id")
                        except Exception:
                            pass

                    if doi and (doi.startswith(("http", "10."))):
                        st.markdown("---")
                        st.markdown("**Add Related Works:**")
                        work_buttons(doi, f"v_{i}")

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_v_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)

        elif search_type == "Full-Text Search":
            # Execute query if needed
            if should_run_query:
                # Full-text search
                results = fulltext_search(
                    f"""SELECT sources.source, sources.text,
                       snippet(fulltext, 1, '{SNIPPET_START}', '{SNIPPET_END}',
                               '...', 16) as snippet,
                       sources.extra
                       FROM fulltext
                       INNER JOIN sources ON fulltext.source = sources.source
                       WHERE fulltext.text MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    query,
                    n_results,
                )

                # Store results in session state
                st.session_state.last_search_results = results
            else:
                # Use cached results
                results = st.session_state.get("last_search_results", [])
                if not results:
                    st.warning("No cached results available")

            # Display results
            for i, (source, text, snippet, extra) in enumerate(results, 1):
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title}"):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(
                        f"**Snippet:** {snippet_html(snippet)}", unsafe_allow_html=True
                    )

                    # Add copy buttons for citation and BibTeX
                    if extra:
                        try:
                            extra_data = json.loads(extra)

                            # Citation copy button
                            if citation:
                                st.markdown("---")
                                st.markdown("**📋 Copy Citation:**")
                                st.code(citation, language="text")

                            # BibTeX copy button
                            from litdb.bibtex import dump_bibtex

                            bibtex = dump_bibtex(extra_data)
                            if bibtex:
                                st.markdown("**📋 Copy BibTeX:**")
                                st.code(bibtex, language="bibtex")
                        except Exception as e:
                            st.error(
                                f"Error generating copy buttons: {e}"
                            )  # Show error for debugging
                    else:
                        st.warning("No metadata available for copy buttons")

                    # Check if this is a DOI/OpenAlex entry to show add buttons
                    doi = None
                    if extra:
                        try:
                            extra_data = json.loads(extra)
                            doi = extra_data.get("doi") or extra_data.get("id")
                        except Exception:
                            pass

                    if doi and (doi.startswith(("http", "10."))):
                        st.markdown("---")
                        st.markdown("**Add Related Works:**")
                        work_buttons(doi, f"fts_{i}")

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_fts_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)

        elif search_type == "Hybrid Search":
            st.info("Hybrid search combines vector and full-text results")

            # Execute queries if needed
            if should_run_query:
                # Vector search
                vector_results = vector_search(query, n_results)

                # Full-text search
                fts_results = fulltext_search(
                    f"""SELECT sources.source, sources.text,
                       snippet(fulltext, 1, '{SNIPPET_START}', '{SNIPPET_END}',
                               '...', 16) as snippet
                       FROM fulltext
                       INNER JOIN sources ON fulltext.source = sources.source
                       WHERE fulltext.text MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    query,
                    n_results,
                )

                # Store both results in session state
                st.session_state.last_search_results = (
                    vector_results  # For iterative search
                )
                st.session_state.last_hybrid_fts_results = fts_results
            else:
                # Use cached results
                vector_results = st.session_state.get("last_search_results", [])
                fts_results = st.session_state.get("last_hybrid_fts_results", [])
                if not vector_results and not fts_results:
                    st.warning("No cached results available")

            st.markdown("**Vector Search Results:**")
            for i, (source, text, extra, distance) in enumerate(vector_results, 1):
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title} (distance: {distance:.4f})"):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Text preview:** {preview(text, 200)}")

                    # Add copy buttons for citation and BibTeX
                    if extra:
                        try:
                            extra_data = json.loads(extra)

                            # Citation copy button
                            if citation:
                                st.markdown("---")
                                st.markdown("**📋 Copy Citation:**")
                                st.code(citation, language="text")

                            # BibTeX copy button
                            from litdb.bibtex import dump_bibtex

                            bibtex = dump_bibtex(extra_data)
                            if bibtex:
                                st.markdown("**📋 Copy BibTeX:**")
                                st.code(bibtex, language="bibtex")
                        except Exception as e:
                            st.error(
                                f"Error generating copy buttons: {e}"
                            )  # Show error for debugging
                    else:
                        st.warning("No metadata available for copy buttons")

                    # Check if this is a DOI/OpenAlex entry to show add buttons
                    doi = None
                    if extra:
                        try:
                            extra_data = json.loads(extra)
                            doi = extra_data.get("doi") or extra_data.get("id")
                        except Exception:
                            pass

                    if doi and (doi.startswith(("http", "10."))):
                        st.markdown("---")
                        st.markdown("**Add Related Works:**")
                        work_buttons(doi, f"hv_{i}")

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_hv_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)

            st.markdown("**Full-Text Search Results:**")
            for i, (source, text, snippet) in enumerate(fts_results, 1):
                # Try to get extra for citation
                extra_result = db.execute(
                    "SELECT extra FROM sources WHERE source = ?", [source]
                ).fetchone()
                extra = extra_result[0] if extra_result else None
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title}"):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(
                        f"**Snippet:** {snippet_html(snippet)}", unsafe_allow_html=True
                    )

                    # Add copy buttons for citation and BibTeX
                    if extra:
                        try:
                            extra_data = json.loads(extra)

                            # Citation copy button
                            if citation:
                                st.markdown("---")
                                st.markdown("**📋 Copy Citation:**")
                                st.code(citation, language="text")

                            # BibTeX copy button
                            from litdb.bibtex import dump_bibtex

                            bibtex = dump_bibtex(extra_data)
                            if bibtex:
                                st.markdown("**📋 Copy BibTeX:**")
                                st.code(bibtex, language="bibtex")
                        except Exception as e:
                            st.error(
                                f"Error generating copy buttons: {e}"
                            )  # Show error for debugging
                    else:
                        st.warning("No metadata available for copy buttons")

                    # Check if this is a DOI/OpenAlex entry to show add buttons
                    doi = None
                    if extra:
                        try:
                            extra_data = json.loads(extra)
                            doi = extra_data.get("doi") or extra_data.get("id")
                        except Exception:
                            pass

                    if doi and (doi.startswith(("http", "10."))):
                        st.markdown("---")
                        st.markdown("**Add Related Works:**")
                        work_buttons(doi, f"hf_{i}")

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_hf_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)

        # Add iterative search button for Vector and Hybrid searches
        if search_type in ["Vector Search", "Hybrid Search"]:
            st.markdown("---")
            st.markdown("### 🔄 Iterative Search")
            st.markdown(
                "Run one iteration to add references, citations, and related works from current results, then re-search for better matches."
            )

            if st.button("▶️ Run One Iteration"):
                # Set flag to trigger iteration processing on next rerun
                st.session_state.run_iteration = True
                st.rerun()


def tab_openalex_search():
    """OpenAlex search tab - search OpenAlex directly and add papers."""
    st.title("🔎 OpenAlex Search")

    st.markdown(
        """
    Search [OpenAlex](https://openalex.org/) directly for academic papers.
    You can add individual papers or their references, citing papers, and related works.
    """
    )

    # Use form to allow Enter key to submit
    with st.form("openalex_search_form"):
        query = st.text_input("Enter your search query")
        n_results = st.slider("Number of results", 1, 50, 10)
        search_submitted = st.form_submit_button("Search OpenAlex")

    if search_submitted:
        if not query:
            st.warning("Please enter a search query")
            return

        from litdb.openalex import get_data

        params = {
            "search": query,
            "mailto": config["openalex"].get("email"),
            "per_page": n_results,
        }
        if config["openalex"].get("api_key"):
            params["api_key"] = config["openalex"].get("api_key")

        try:
            with st.spinner("Searching OpenAlex..."):
                data = get_data("https://api.openalex.org/works", params)
        except Exception as e:
            st.error(f"Error searching OpenAlex: {e}")
            return
        # The results are kept in the session, because clicking one of their
        # buttons reruns the script, and then the form is not submitted.
        st.session_state["oa_results"] = data.get("results", [])

    results = st.session_state.get("oa_results")
    if results is None:
        return

    st.subheader("Results from OpenAlex")
    if not results:
        st.info("No results found")
        return

    st.success(f"Found {len(results)} papers")

    for i, work in enumerate(results, 1):
        title = work.get("title") or "No title"
        doi = work.get("doi") or work.get("id")
        publication_year = work.get("publication_year")
        citation_count = work.get("cited_by_count", 0)
        author_str = ", ".join(author_names(work)) or "No authors"

        header = f"{i}. {title}"
        if publication_year:
            header += f" ({publication_year})"

        with st.expander(header):
            st.markdown(f"**Authors:** {author_str}")
            if doi:
                st.markdown(f"**DOI/ID:** {doi}")
            st.markdown(f"**Citations:** {citation_count}")

            pl = work.get("primary_location") or {}
            venue_name = (pl.get("source") or {}).get("display_name")
            if venue_name:
                st.markdown(f"**Venue:** {venue_name}")

            if abstract := abstract_text(work):
                st.markdown(f"**Abstract:** {preview(abstract, 500)}")

            st.markdown("---")
            if doi:
                work_buttons(doi, f"oa_{i}", add_paper=True)

            if st.checkbox("Show full metadata", key=f"meta_oa_{i}"):
                st.json(work)


def semantic_scholar_id(paper):
    """Return an id of the Semantic Scholar PAPER that OpenAlex knows, or None."""
    external_ids = paper.get("externalIds") or {}
    if doi := external_ids.get("DOI"):
        return doi if doi.startswith("http") else f"https://doi.org/{doi}"
    if arxiv_id := external_ids.get("ArXiv"):
        # OpenAlex knows arXiv papers by their DataCite DOI, not their arxiv url.
        return f"https://doi.org/10.48550/arXiv.{arxiv_id}"
    return None


def tab_semantic_scholar_search():
    """Semantic Scholar search tab - search Semantic Scholar directly and add papers."""
    st.title("📖 Semantic Scholar Search")

    st.markdown(
        """
    Search [Semantic Scholar](https://www.semanticscholar.org/) directly for academic papers.
    You can add individual papers or their references, citing papers, and related works.
    """
    )

    # Use form to allow Enter key to submit
    with st.form("semantic_scholar_search_form"):
        query = st.text_input("Enter your search query")
        n_results = st.slider("Number of results", 1, 50, 10)
        search_submitted = st.form_submit_button("Search Semantic Scholar")

    if search_submitted:
        if not query:
            st.warning("Please enter a search query")
            return

        import requests

        params = {
            "query": query,
            "limit": n_results,
            "fields": "title,authors,year,citationCount,externalIds,abstract,venue",
        }

        headers = {}
        api_key = (config.get("semantic-scholar") or {}).get("api_key")
        if api_key:
            headers["x-api-key"] = api_key

        try:
            with st.spinner("Searching Semantic Scholar..."):
                response = requests.get(
                    "https://api.semanticscholar.org/graph/v1/paper/search",
                    params=params,
                    headers=headers,
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            st.error(f"Error searching Semantic Scholar: {e}")
            return
        st.session_state["ss_results"] = data.get("data") or []

    results = st.session_state.get("ss_results")
    if results is None:
        return

    st.subheader("Results from Semantic Scholar")
    if not results:
        st.info("No results found")
        return

    st.success(f"Found {len(results)} papers")

    for i, paper in enumerate(results, 1):
        title = paper.get("title") or "No title"
        publication_year = paper.get("year")
        citation_count = paper.get("citationCount", 0)
        venue = paper.get("venue", "")
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI")
        arxiv_id = external_ids.get("ArXiv")

        paper_authors = paper.get("authors") or []
        authors = [a.get("name") or "Unknown" for a in paper_authors[:3]]
        if len(paper_authors) > 3:
            authors.append("et al.")
        author_str = ", ".join(authors) or "No authors"

        header = f"{i}. {title}"
        if publication_year:
            header += f" ({publication_year})"

        with st.expander(header):
            st.markdown(f"**Authors:** {author_str}")
            if doi:
                st.markdown(f"**DOI:** {doi}")
            elif arxiv_id:
                st.markdown(f"**arXiv:** {arxiv_id}")
            if venue:
                st.markdown(f"**Venue:** {venue}")
            st.markdown(f"**Citations:** {citation_count}")

            abstract = paper.get("abstract")
            if abstract and st.checkbox("📄 Show Abstract", key=f"abstract_ss_{i}"):
                st.write(abstract)

            st.markdown("---")
            if paper_id := semantic_scholar_id(paper):
                st.markdown("**Add to Library:**")
                work_buttons(paper_id, f"ss_{i}", add_paper=True)
            else:
                st.caption("This paper has no DOI or arXiv id to add it with.")

            if st.checkbox("Show full metadata", key=f"meta_ss_{i}"):
                st.json(paper)


def reviewer_rows(results):
    """Return (author_counts, author_data) for the vector search RESULTS.

    author_counts counts the papers of each OpenAlex author id, and author_data
    has the OpenAlex details of each author.
    """
    from collections import Counter

    from more_itertools import batched

    from litdb.openalex import get_data

    authors = []
    for _source, _text, extra, _distance in results:
        try:
            d = json.loads(extra) if extra else {}
        except json.JSONDecodeError:
            continue
        # Only OpenAlex works have authorships; files and web pages do not.
        for authorship in (d or {}).get("authorships") or []:
            if author_id := (authorship.get("author") or {}).get("id"):
                authors.append(author_id)
    author_counts = Counter(authors)

    author_data = []
    for batch in batched(author_counts, 50):
        url = f"https://api.openalex.org/authors?filter=id:{'|'.join(batch)}"
        params = {
            "per-page": 50,
            "mailto": (config.get("openalex") or {}).get("email", ""),
        }
        for d in get_data(url, params).get("results") or []:
            lki = d.get("last_known_institutions") or []
            affils = d.get("affiliations") or []
            if lki:
                institution = lki[0].get("display_name") or "Unknown"
            elif affils:
                institution = (affils[0].get("institution") or {}).get(
                    "display_name"
                ) or "Unknown"
            else:
                institution = "Unknown"

            author_data.append(
                {
                    "name": d.get("display_name") or "Unknown",
                    "papers": author_counts.get(d["id"], 0),
                    "h_index": (d.get("summary_stats") or {}).get("h_index") or 0,
                    "id": d["id"],
                    "institution": institution,
                    "works_count": d.get("works_count") or 0,
                }
            )

    # Sort by h-index (primary) and number of papers (secondary)
    author_data.sort(key=lambda x: (x["h_index"], x["papers"]), reverse=True)
    return author_counts, author_data


def tab_suggest_reviewers():
    """Suggest Reviewers tab - find potential reviewers based on similar papers."""
    st.title("👥 Suggest Reviewers")

    st.markdown(
        """
    Find potential reviewers by searching for papers similar to your topic.
    The system will identify authors from the most relevant papers in your database
    and rank them by h-index and number of relevant publications.
    """
    )

    # Use form to allow Enter key to submit
    with st.form("suggest_reviewers_form"):
        query = st.text_input(
            "Enter your research topic or abstract",
            help="Describe your research to find authors who have published similar work",
        )
        n_papers = st.slider("Number of similar papers to analyze", 5, 20, 10)
        search_submitted = st.form_submit_button("Find Reviewers")

    if search_submitted:
        if not query:
            st.warning("Please enter a research topic or query")
            return

        st.subheader("Results")

        try:
            with st.spinner("Searching for similar papers..."):
                results = vector_search(query, n_papers)

            if not results:
                st.warning("No similar papers found in your database")
                return

            st.markdown(f"**Found {len(results)} similar papers**")

            with st.expander("📄 View similar papers used for reviewer suggestions"):
                for i, (source, _text, extra, distance) in enumerate(results, 1):
                    citation = format_citation(extra) if extra else None
                    st.markdown(
                        f"{i}. {citation or source} (similarity: {1 - distance:.3f})"
                    )

            with st.spinner("Fetching author details from OpenAlex..."):
                author_counts, author_data = reviewer_rows(results)

            if not author_counts:
                st.warning("No author information found in the similar papers")
                return

            st.markdown("### 🎯 Suggested Reviewers")
            st.markdown(
                f"*Ranked by h-index and number of relevant publications ({len(author_data)} total)*"
            )

            for i, author in enumerate(author_data[:20], 1):  # Show top 20
                with st.container():
                    col1, col2, col3, col4 = st.columns([3, 1, 1, 2])

                    with col1:
                        st.markdown(f"**{i}. {author['name']}**")
                        st.caption(author["institution"])

                    with col2:
                        st.metric("H-Index", author["h_index"])

                    with col3:
                        st.metric("Relevant Papers", author["papers"])

                    with col4:
                        st.caption(f"Total works: {author['works_count']}")
                        oa_url = author["id"].replace(
                            "https://openalex.org/", "https://openalex.org/authors/"
                        )
                        st.markdown(f"[View Profile]({oa_url})")

                    st.markdown("---")

            if author_data:
                with st.expander("📊 View full data table"):
                    df = pd.DataFrame(author_data)
                    st.dataframe(
                        df[["name", "papers", "h_index", "works_count", "institution"]],
                        use_container_width=True,
                    )
                    st.download_button(
                        label="Download as CSV",
                        data=df.to_csv(index=False),
                        file_name="suggested_reviewers.csv",
                        mime="text/csv",
                    )

        except Exception as e:
            st.error(f"Error suggesting reviewers: {e}")
            import traceback

            st.code(traceback.format_exc())


def rag_prompt(prompt, rag_content):
    """Return PROMPT with the retrieved RAG_CONTENT to answer it with."""
    return f"""Use the following retrieved information to respond to
the user prompt. Reference the citations if you use that information.

<retrieved information>
{rag_content}

<user prompt>
{prompt}"""


def tab_chat():
    """Chat tab with RAG functionality (original chat interface)."""
    st.title("💬 Chat with Your Library")

    # Initialize session state
    if "model" not in st.session_state:
        st.session_state["model"] = gpt["model"]

    if "messages" not in st.session_state:
        st.session_state.messages = []

    # Display chat history
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Chat input
    if prompt := st.chat_input("What would you like to know?"):
        with st.chat_message("user"):
            st.markdown(prompt)

        rag_content, references = get_rag_content(prompt, 3)

        # The history keeps what the user typed. The retrieved text is only sent
        # with the current prompt, so it is not redisplayed, and old retrievals
        # do not pile up in every later request.
        st.session_state.messages.append({"role": "user", "content": prompt})
        messages = [
            *st.session_state.messages[:-1],
            {"role": "user", "content": rag_prompt(prompt, rag_content)},
        ]

        with st.chat_message("assistant"):
            stream = completion(
                model=st.session_state["model"],
                messages=messages,
                stream=True,
            )

            message_placeholder = st.empty()
            full_response = ""
            for chunk in stream:
                full_response += chunk.choices[0].delta.content or ""
                message_placeholder.markdown(full_response)

            st.markdown("**References used:**")
            st.markdown(references)

            msg = {"role": "assistant", "content": full_response}
            st.session_state.messages.append(msg)


def add_source_item(source):
    """Add SOURCE (a DOI, ORCID, url or file) and return the key it is stored under.

    This is what `litdb add` does for one source, so the app and the command
    line agree. Authors and bibtex files add many works and return None.
    """
    from litdb.commands.manage import _add_one

    return _add_one(source, False, False, False, True, None, None, None, False)


def save_upload(uploaded_file):
    """Save the UPLOADED_FILE in the litdb root and return its path.

    The file is the source of its entry, so it has to stay where it is (a
    temporary file would leave the entry pointing at a deleted file).
    """
    import pathlib

    upload_dir = pathlib.Path(config["root"]) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    path = upload_dir / pathlib.Path(uploaded_file.name).name
    stem, suffix, n = path.stem, path.suffix, 1
    while path.exists() and path.read_bytes() != uploaded_file.getvalue():
        path = upload_dir / f"{stem}-{n}{suffix}"
        n += 1
    path.write_bytes(uploaded_file.getvalue())
    return str(path)


def add_bibtex_text(bibtex):
    """Add the works with a DOI in the BIBTEX string."""
    import tempfile

    from litdb.db import add_bibtex

    with tempfile.TemporaryDirectory() as d:
        bibfile = os.path.join(d, "entries.bib")
        with open(bibfile, "w", encoding="utf-8") as f:
            f.write(bibtex)
        add_bibtex(bibfile)


def show_added_work(source, key):
    """Show the work SOURCE that was just added, with its tags and actions."""
    row = db.execute("SELECT extra FROM sources WHERE source = ?", (source,)).fetchone()
    extra = row[0] if row else None
    try:
        extra_data = json.loads(extra) if extra else {}
    except json.JSONDecodeError:
        extra_data = {}
    citation = format_citation(extra) if extra else None
    title = extra_data.get("display_name") or source

    with st.expander(f"📄 {preview(title, 80)}", expanded=False):
        st.markdown(f"**Citation:** {citation or source}")
        st.markdown(f"**Source:** {source}")
        if authors := author_names(extra_data, limit=5):
            st.markdown(f"**Authors:** {', '.join(authors)}")

        st.markdown("---")
        st.markdown("**📋 Copy Citation:**")
        st.code(citation or source, language="text")
        try:
            bibtex = dump_bibtex(extra_data) if extra_data else None
        except Exception:
            bibtex = None
        if bibtex:
            st.markdown("**📋 Copy BibTeX:**")
            st.code(bibtex, language="bibtex")

        st.markdown("---")
        tag_editor(source, key)

        st.markdown("---")
        st.markdown("**Add Related Works:**")
        work_buttons(source, key)


def tab_add_content():
    """Add content tab for adding new sources."""
    st.title("➕ Add Content")

    add_method = st.selectbox(
        "Add Method",
        ["From Text", "DOI", "ORCID", "BibTeX", "File or URL", "Directory (Recursive)"],
    )

    if add_method == "DOI":
        st.subheader("Add by DOI")

        with st.form("doi_form"):
            doi_input = st.text_area("Enter DOI(s), one per line")
            doi_submitted = st.form_submit_button("Add DOI(s)")

        if doi_submitted:
            dois = [d.strip() for d in (doi_input or "").split("\n") if d.strip()]
            if not dois:
                st.warning("Please enter at least one DOI")
                return

            st.info(f"Adding {len(dois)} DOI(s)...")
            added, failed = [], []
            progress_bar = st.progress(0)
            status_text = st.empty()

            for idx, doi in enumerate(dois, 1):
                status_text.text(f"Processing {idx}/{len(dois)}: {doi}")
                try:
                    added.append(add_work(doi))
                except Exception as e:
                    failed.append((doi, str(e)))
                progress_bar.progress(idx / len(dois))

            progress_bar.empty()
            status_text.empty()
            # Kept in the session, so the tag and related-work buttons of the
            # added works still work after their click reruns the script.
            st.session_state["doi_added"] = added
            st.session_state["doi_failed"] = failed

        added = st.session_state.get("doi_added") or []
        failed = st.session_state.get("doi_failed") or []
        if added:
            st.success(f"Successfully added {len(added)} work(s)!")
            st.markdown("---")
            st.subheader("Added Works Summary")
            for idx, source in enumerate(added):
                show_added_work(source, f"add_{idx}")

        if failed:
            st.error(f"Failed to add {len(failed)} work(s)")
            with st.expander("Show failed works"):
                for doi, error in failed:
                    st.text(f"❌ {doi}: {error}")

    elif add_method == "ORCID":
        st.subheader("Add by ORCID")
        st.markdown("Adds all the works of an author, by ORCID or OpenAlex author id.")

        with st.form("orcid_form"):
            orcid = st.text_input(
                "Enter ORCID ID", placeholder="0000-0003-2625-9232"
            ).strip()
            orcid_submitted = st.form_submit_button("Add Works")

        if orcid_submitted:
            if not orcid:
                st.warning("Please enter an ORCID ID")
                return
            try:
                with st.spinner(f"Adding the works of {orcid}..."):
                    add_source_item(orcid)
                st.success(f"✓ Added the works of {orcid}")
            except Exception as e:
                st.error(f"Failed to add the works of {orcid}: {e}")

    elif add_method == "BibTeX":
        st.subheader("Add from BibTeX")
        st.markdown("Entries with a DOI are added from OpenAlex.")

        with st.form("bibtex_form"):
            bibtex_input = st.text_area("Paste BibTeX entries", height=200)
            bibtex_submitted = st.form_submit_button("Add from BibTeX")

        if bibtex_submitted:
            if not bibtex_input.strip():
                st.warning("Please paste BibTeX entries")
                return
            try:
                with st.spinner("Adding BibTeX entries..."):
                    add_bibtex_text(bibtex_input)
                st.success("✓ Added the BibTeX entries with a DOI")
            except Exception as e:
                st.error(f"Failed to add BibTeX entries: {e}")

    elif add_method == "From Text":
        st.subheader("Extract References from Text")
        st.markdown("""
        Paste text containing references (e.g., from a paper's reference section)
        and the LLM will extract and match them to DOIs.
        """)

        with st.form("fromtext_form"):
            text_input = st.text_area("Paste text with references", height=200)
            fromtext_submitted = st.form_submit_button("Extract References")

        if fromtext_submitted:
            if text_input:
                from difflib import SequenceMatcher

                import requests

                from litdb.chat import get_completion

                with st.spinner("Extracting references using LLM..."):
                    # Step 1: Use LLM to extract references
                    messages = [
                        {
                            "role": "user",
                            "content": f"""Extract all academic references from the following text.
For each reference, provide a JSON object with these fields:
- title (string, required)
- authors (array of strings, can be empty array if not found)
- year (integer or null)
- journal (string or null)
- doi (string or null)

Return ONLY a valid JSON array. Example format:
[{{"title": "Example Title", "authors": ["Smith, J.", "Doe, A."], "year": 2020, "journal": "Nature", "doi": "10.1234/example"}}]

Do not include any markdown formatting, explanatory text, or code blocks. Just the raw JSON array.

Text:
{text_input}""",
                        }
                    ]

                    try:
                        llm_output = get_completion(gpt["model"], messages)

                        # Clean up LLM output
                        llm_output = llm_output.strip()
                        if llm_output.startswith("```"):
                            lines = llm_output.split("\n")
                            llm_output = "\n".join(
                                [
                                    line
                                    for line in lines
                                    if not line.startswith("```")
                                    and not line.startswith("json")
                                ]
                            )

                        parsed_refs = json.loads(llm_output)

                        if not isinstance(parsed_refs, list):
                            st.error("LLM did not return a list of references")
                        elif len(parsed_refs) == 0:
                            st.warning("No references found in the text")
                        else:
                            st.success(f"Found {len(parsed_refs)} reference(s)!")
                            st.subheader("Extracted References")

                            results = []

                            # Step 2: Process each reference
                            for i, ref in enumerate(parsed_refs, 1):
                                title = ref.get("title", "")
                                authors = ref.get("authors", [])
                                year = ref.get("year")
                                journal = ref.get("journal", "")
                                doi = ref.get("doi")

                                author_str = (
                                    ", ".join(authors[:3])
                                    if authors
                                    else "Unknown authors"
                                )
                                if len(authors) > 3:
                                    author_str += " et al."

                                citation = f"{author_str} ({year or 'n.d.'}). {title}. {journal or ''}"

                                result = {
                                    "citation": citation,
                                    "title": title,
                                    "authors": author_str,
                                    "year": year,
                                    "journal": journal,
                                    "doi": None,
                                    "confidence": "Low",
                                    "match_info": "",
                                }

                                # If DOI exists, use it directly
                                if doi and doi.strip():
                                    doi_clean = doi.strip()
                                    if not doi_clean.startswith("http"):
                                        doi_clean = f"https://doi.org/{doi_clean}"
                                    result["doi"] = doi_clean
                                    result["confidence"] = "High"
                                    result["match_info"] = "DOI from reference"
                                else:
                                    # Try CrossRef search
                                    query_parts = []
                                    if title:
                                        query_parts.append(title)
                                    if authors:
                                        query_parts.extend(authors[:2])
                                    if year:
                                        query_parts.append(str(year))

                                    query = " ".join(query_parts)

                                    try:
                                        resp = requests.get(
                                            "https://api.crossref.org/works",
                                            params={"query": query, "rows": 1},
                                            timeout=30,
                                        )

                                        if resp.status_code == 200:
                                            data = resp.json()
                                            items = data.get("message", {}).get(
                                                "items", []
                                            )

                                            if items:
                                                best = items[0]
                                                best_title = (
                                                    " ".join(best.get("title", [""]))
                                                    if best.get("title")
                                                    else ""
                                                )
                                                similarity = SequenceMatcher(
                                                    None,
                                                    title.lower(),
                                                    best_title.lower(),
                                                ).ratio()

                                                year_match = False
                                                if year and best.get("published"):
                                                    pub_year = best.get(
                                                        "published", {}
                                                    ).get("date-parts", [[None]])[0][0]
                                                    year_match = pub_year == year

                                                if (
                                                    similarity > 0.7
                                                ):  # Lower threshold for auto-add in web UI
                                                    best_doi = (
                                                        f"https://doi.org/{best['DOI']}"
                                                    )
                                                    result["doi"] = best_doi
                                                    result["confidence"] = (
                                                        "High"
                                                        if similarity > 0.85
                                                        and (year_match or not year)
                                                        else "Medium"
                                                    )
                                                    result["match_info"] = (
                                                        f"CrossRef match (similarity: {similarity:.2f})"
                                                    )

                                    except Exception:
                                        pass

                                results.append(result)

                            # Collect DOIs to add
                            dois_to_add = [r["doi"] for r in results if r["doi"]]
                            failed_refs = [r for r in results if not r["doi"]]

                            successfully_added = []
                            failed_to_add = []

                            # Add to database
                            if dois_to_add:
                                st.subheader("Adding to Database")
                                progress_bar = st.progress(0)
                                status_text = st.empty()

                                for i, doi in enumerate(dois_to_add):
                                    status_text.text(
                                        f"Adding {i + 1}/{len(dois_to_add)}: {doi}"
                                    )
                                    try:
                                        # Import and call the add functionality

                                        add_work(
                                            doi,
                                            references=False,
                                            related=False,
                                            citing=False,
                                        )
                                        successfully_added.append(doi)
                                    except Exception as e:
                                        failed_to_add.append((doi, str(e)))

                                    progress_bar.progress((i + 1) / len(dois_to_add))

                                status_text.empty()
                                progress_bar.empty()

                                # Show results summary
                                st.success(
                                    f"✓ Successfully added {len(successfully_added)} references to database!"
                                )

                                if failed_to_add:
                                    with st.expander(
                                        f"⚠ Failed to add {len(failed_to_add)} references"
                                    ):
                                        for doi, error in failed_to_add:
                                            st.error(f"{doi}: {error}")

                            # Show detailed results
                            st.subheader("Detailed Results")

                            # Successfully added
                            if successfully_added:
                                with st.expander(
                                    f"✓ Added {len(successfully_added)} references",
                                    expanded=False,
                                ):
                                    for i, result in enumerate(
                                        [
                                            r
                                            for r in results
                                            if r["doi"] in successfully_added
                                        ],
                                        1,
                                    ):
                                        st.markdown(f"**{i}. {result['title']}**")
                                        st.markdown(
                                            f"   - Authors: {result['authors']}"
                                        )
                                        st.markdown(
                                            f"   - DOI: [{result['doi']}]({result['doi']})"
                                        )
                                        st.markdown(
                                            f"   - Confidence: {result['confidence']} ({result['match_info']})"
                                        )

                            # Failed to find DOI
                            if failed_refs:
                                with st.expander(
                                    f"⚠ Could not add {len(failed_refs)} references (no DOI found)",
                                    expanded=True,
                                ):
                                    st.warning(
                                        "These references could not be matched to a DOI via CrossRef. They may need manual lookup."
                                    )
                                    for i, result in enumerate(failed_refs, 1):
                                        st.markdown(f"**{i}. {result['title']}**")
                                        st.markdown(
                                            f"   - Authors: {result['authors']}"
                                        )
                                        st.markdown(
                                            f"   - Year: {result['year'] or 'Unknown'}"
                                        )
                                        if result["journal"]:
                                            st.markdown(
                                                f"   - Journal: {result['journal']}"
                                            )

                            # Overall summary
                            st.markdown("---")
                            st.info(f"""
**Summary:**
- Found {len(results)} references in text
- Added {len(successfully_added)} to database
- Could not find DOI for {len(failed_refs)} references
- Failed to add {len(failed_to_add)} references
""")

                    except json.JSONDecodeError as e:
                        st.error(f"Error parsing LLM output as JSON: {e}")
                    except Exception as e:
                        st.error(f"Error extracting references: {e}")

            else:
                st.warning("Please paste text with references")

    elif add_method == "File or URL":
        st.subheader("Add File or URL")
        st.markdown("""
        Upload a file or provide a URL to add to your library.
        Supported formats: PDF, DOCX, PPTX, HTML, Jupyter notebooks, BibTeX, and more.
        Uploaded files are kept in the `uploads` directory of your litdb root.
        """)

        input_type = st.radio("Input Type", ["File Upload", "URL"])

        if input_type == "File Upload":
            with st.form("file_upload_form"):
                uploaded_file = st.file_uploader(
                    "Choose a file",
                    type=[
                        "pdf",
                        "docx",
                        "pptx",
                        "html",
                        "bib",
                        "ipynb",
                        "txt",
                        "md",
                        "org",
                    ],
                )
                file_submitted = st.form_submit_button("Add File")

            if file_submitted and uploaded_file:
                try:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        add_source_item(save_upload(uploaded_file))
                    st.success(f"✓ Successfully added: {uploaded_file.name}")
                except Exception as e:
                    st.error(f"Failed to add file: {e}")

        else:  # URL
            with st.form("url_form"):
                url_input = st.text_input(
                    "Enter URL", placeholder="https://example.com/article"
                ).strip()
                url_submitted = st.form_submit_button("Add URL")

            if url_submitted:
                if url_input:
                    try:
                        with st.spinner(f"Processing {url_input}..."):
                            add_source_item(url_input)
                        st.success(f"✓ Successfully added: {url_input}")
                    except Exception as e:
                        st.error(f"Failed to add URL: {e}")
                else:
                    st.warning("Please enter a URL")

    elif add_method == "Directory (Recursive)":
        st.subheader("Index Directory Recursively")
        st.markdown("""
        Index all supported files in a directory and its subdirectories.
        Supported formats: PDF, DOCX, PPTX, Org, Markdown, HTML, BibTeX, Jupyter notebooks.
        """)

        with st.form("directory_form"):
            directory_path = st.text_input(
                "Directory Path", placeholder="/path/to/your/documents"
            ).strip()
            directory_submitted = st.form_submit_button("Index Directory")

        if directory_submitted:
            if not directory_path:
                st.warning("Please enter a directory path")
                return

            import pathlib

            from litdb.commands.manage import _files_to_index, _record_indexed

            dir_path = pathlib.Path(directory_path).expanduser()
            if not dir_path.exists():
                st.error(f"Directory does not exist: {directory_path}")
                return
            if not dir_path.is_dir():
                st.error(f"Path is not a directory: {directory_path}")
                return

            try:
                new_files = _files_to_index(db, dir_path)
                successfully_added, failed_to_add = [], []

                if not new_files:
                    st.info(
                        f"No new files found in {directory_path} (all files already indexed)"
                    )
                else:
                    st.info(f"Found {len(new_files)} new file(s) to index")
                    progress_bar = st.progress(0)
                    status_text = st.empty()

                    for i, fname in enumerate(new_files):
                        status_text.text(
                            f"Adding {i + 1}/{len(new_files)}: {fname.name}"
                        )
                        try:
                            add_source_item(str(fname))
                            successfully_added.append(fname)
                        except Exception as e:
                            failed_to_add.append((fname, str(e)))
                        progress_bar.progress((i + 1) / len(new_files))

                    status_text.empty()
                    progress_bar.empty()

                # Recorded so `litdb reindex` keeps it up to date.
                _record_indexed(db, dir_path)

                if new_files:
                    st.success(
                        f"✓ Successfully indexed {len(successfully_added)} file(s)!"
                    )

                if failed_to_add:
                    with st.expander(f"⚠ Failed to add {len(failed_to_add)} file(s)"):
                        for fname, error in failed_to_add:
                            st.error(f"{fname.name}: {error}")

                if successfully_added:
                    with st.expander(
                        f"✓ Indexed {len(successfully_added)} files", expanded=False
                    ):
                        for fname in successfully_added:
                            st.markdown(f"- {fname}")

            except Exception as e:
                st.error(f"Error indexing directory: {e}")


def tab_library_browser():
    """Library browser tab for browsing sources."""
    st.title("📚 Library Browser")

    view_mode = st.selectbox("View Mode", ["Recent Additions", "By Tags", "Timeline"])

    if view_mode == "Recent Additions":
        st.subheader("Recent Additions")
        days = st.slider("Show additions from last N days", 1, 90, 7)

        results = db.execute(
            """SELECT source, text, date_added, extra
               FROM sources
               WHERE date_added > datetime('now', ?)
               ORDER BY date_added DESC
               LIMIT 50""",
            [f"-{days} days"],
        ).fetchall()

        if results:
            for source, text, date_added, extra in results:
                title = source_title(source, extra)
                with st.expander(f"{preview(title, 80)} (Added: {date_added})"):
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Preview:** {preview(text, 200)}")
        else:
            st.info(f"No additions in the last {days} days")

    elif view_mode == "By Tags":
        st.subheader("Browse by Tags")

        # Get all tags
        tags = db.execute("SELECT DISTINCT tag FROM tags ORDER BY tag").fetchall()

        if tags:
            tag_list = [t[0] for t in tags]
            selected_tag = st.selectbox("Select Tag", tag_list)

            if selected_tag:
                results = db.execute(
                    """SELECT s.source, s.text, s.extra
                       FROM sources s
                       JOIN source_tag st ON s.rowid = st.source_id
                       JOIN tags t ON st.tag_id = t.rowid
                       WHERE t.tag = ?
                       ORDER BY s.source""",
                    [selected_tag],
                ).fetchall()

                st.markdown(f"**{len(results)} sources with tag '{selected_tag}'**")

                for source, text, extra in results:
                    with st.expander(preview(source_title(source, extra), 80)):
                        st.markdown(f"**Source:** {source}")
                        st.markdown(f"**Preview:** {preview(text, 200)}")
        else:
            st.info("No tags found in database")

    elif view_mode == "Timeline":
        st.subheader("Timeline View")
        st.info("Visualizing additions over time...")

        # Get counts by month
        timeline_data = db.execute(
            """SELECT date(date_added, 'start of month') as month,
               count(*) as count
               FROM sources
               WHERE date_added IS NOT NULL
               GROUP BY month
               ORDER BY month DESC
               LIMIT 24"""
        ).fetchall()

        if timeline_data:
            df = pd.DataFrame(timeline_data, columns=["Month", "Count"])
            st.bar_chart(df.set_index("Month"))
        else:
            st.info("No timeline data available")


def save_query(filter_expr, description):
    """Save the OpenAlex FILTER_EXPR, as `litdb add-filter` does.

    Returns False if there is already a query with that filter.
    """
    if db.execute("SELECT 1 FROM queries WHERE filter = ?", (filter_expr,)).fetchone():
        return False
    db.execute(
        "INSERT INTO queries(filter, description) VALUES (?, ?)",
        (filter_expr, description or None),
    )
    db.commit()
    return True


def delete_query(filter_expr):
    """Delete the query with FILTER_EXPR, as `litdb rm-filter` does."""
    db.execute("DELETE FROM queries WHERE filter = ?", (filter_expr,))
    db.commit()


def tab_manage_filters():
    """Manage filters tab for queries and searches."""
    st.title("⚙️ Manage Filters & Queries")

    st.markdown("""
    Manage saved search filters and queries. These are used by the CLI's `watch` and `follow` commands.
    """)

    # Custom CSS for light blue button
    st.markdown(
        """
    <style>
    div.stButton > button[kind="secondary"] {
        background-color: #4A90E2;
        color: white;
        border: none;
    }
    div.stButton > button[kind="secondary"]:hover {
        background-color: #357ABD;
        color: white;
    }
    </style>
    """,
        unsafe_allow_html=True,
    )

    # Update all filters button at the top
    if st.button(
        "🔄 Update All Filters", use_container_width=True, key="update_filters_btn"
    ):
        st.session_state.update_filters_clicked = True
        st.rerun()

    # Process filter updates if button was clicked
    if st.session_state.get("update_filters_clicked", False):
        st.session_state.update_filters_clicked = False

        # Import here where we actually use it
        import os

        from litdb.db import update_filter

        # Set offline mode to speed up embeddings
        os.environ["TRANSFORMERS_OFFLINE"] = "1"

        # Get all filters
        filters = db.execute(
            "SELECT filter, description, last_updated FROM queries"
        ).fetchall()

        if not filters:
            st.info("No filters to update")
        else:
            st.markdown("---")
            st.subheader(f"Updating {len(filters)} Filters")

            # Container for results and errors
            all_results = {}
            total_new_works = 0
            errors = []

            # Progress bar
            progress_bar = st.progress(0)
            status_text = st.empty()

            for idx, (filter_expr, description, last_updated) in enumerate(filters, 1):
                status_text.markdown(
                    f"**Processing filter {idx}/{len(filters)}:** `{filter_expr[:50]}...`"
                )

                try:
                    # Update this filter
                    results = update_filter(filter_expr, last_updated, silent=True)

                    if results:
                        all_results[filter_expr] = {
                            "description": description,
                            "results": results,
                            "count": len(results),
                        }
                        total_new_works += len(results)
                        status_text.success(
                            f"✓ Filter {idx}/{len(filters)}: Found {len(results)} new works"
                        )
                    else:
                        status_text.info(f"✓ Filter {idx}/{len(filters)}: No new works")

                except Exception as e:
                    error_msg = f"Filter {idx}: {e!s}"
                    errors.append(error_msg)
                    status_text.error(f"✗ Filter {idx}/{len(filters)}: Error - {e!s}")

                progress_bar.progress(idx / len(filters))

            # Clear progress indicators
            progress_bar.empty()
            status_text.empty()

            # Display summary
            if total_new_works > 0:
                st.success(
                    f"✓ Update complete! Processed **{len(filters)}** filters. "
                    f"Added **{total_new_works}** new works from **{len(all_results)}** filter(s)."
                )
            else:
                st.info(
                    f"✓ Update complete! Processed **{len(filters)}** filters. "
                    f"No new works found (all filters are up to date)."
                )

            # Show errors if any occurred
            if errors:
                st.warning(f"⚠️ {len(errors)} filter(s) had errors:")
                with st.expander("Show errors"):
                    for error in errors[:20]:  # Show first 20
                        st.text(error)
                    if len(errors) > 20:
                        st.text(f"... and {len(errors) - 20} more errors")

            # Display results organized by filter
            if all_results:
                st.markdown("---")
                st.subheader("New Results by Filter")

                for filter_expr, data in all_results.items():
                    description = data["description"] or "No description"
                    count = data["count"]
                    results = data["results"]

                    with st.expander(
                        f"**{description}** ({count} new works) - `{filter_expr}`",
                        expanded=False,
                    ):
                        for i, (source, text, extra) in enumerate(results[:10], 1):
                            # Format citation
                            try:
                                citation = format_citation(json.dumps(extra))
                                st.markdown(f"{i}. {citation}")
                            except Exception:
                                st.markdown(f"{i}. {source}")

                        if count > 10:
                            st.info(f"... and {count - 10} more works")

    st.markdown("---")

    # Add new query
    st.subheader("Add New Query")

    with st.form("new_query_form"):
        new_filter = st.text_input(
            "Filter Expression",
            placeholder="e.g., author.id:A1234567890",
            help="OpenAlex filter expression",
        )
        new_description = st.text_area(
            "Description (optional)", placeholder="What this query tracks..."
        )

        if st.form_submit_button("Save Query"):
            if new_filter.strip():
                if save_query(new_filter.strip(), new_description.strip()):
                    st.success(f"Query saved: {new_filter}")
                else:
                    st.warning(f"There is already a query for {new_filter}")
            else:
                st.warning("Please enter a filter expression")

    st.markdown("---")

    # Show existing filters/queries
    st.subheader("Saved Queries")

    queries = db.execute(
        "SELECT filter, description, last_updated FROM queries ORDER BY last_updated DESC"
    ).fetchall()

    if queries:
        st.markdown(f"**{len(queries)} saved queries:**")

        for i, (filter_text, description, last_updated) in enumerate(queries):
            # Show filter and description clearly
            st.markdown(f"**Filter:** `{filter_text}`")
            if description:
                st.markdown(f"*{description}*")
            else:
                st.markdown("*No description*")

            # Show metadata and actions in columns
            col1, col2, col3 = st.columns([3, 2, 1])
            with col1:
                st.caption(f"Last updated: {last_updated}")
            with col3:
                if st.button("Delete", key=f"delete_query_{i}"):
                    delete_query(filter_text)
                    st.rerun()

            # Add expander to show articles belonging to this filter
            # We'll match based on the OpenAlex ID pattern in the filter
            # For author.id filters, we can search for that author ID in the extra field
            with st.expander("📚 Show articles from this filter"):
                # Use a button to trigger lazy loading
                load_key = f"load_articles_{i}"
                if load_key not in st.session_state:
                    st.session_state[load_key] = False

                if not st.session_state[load_key]:
                    if st.button("Load articles", key=f"btn_{load_key}"):
                        st.session_state[load_key] = True
                        st.rerun()
                else:
                    try:
                        # Query all sources and filter based on the filter expression
                        # This is a simplified approach - we look for articles in the database
                        # that contain the filter ID in their extra metadata

                        # Extract the ID from the filter (e.g., "author.id:A123" -> "A123")
                        filter_parts = filter_text.split(":")
                        if len(filter_parts) >= 2:
                            filter_id = ":".join(
                                filter_parts[1:]
                            )  # Handle IDs with colons

                            # Query for articles that might match this filter
                            articles = db.execute(
                                "SELECT source, text, extra FROM sources WHERE extra LIKE ? LIMIT 50",
                                (f"%{filter_id}%",),
                            ).fetchall()

                            if articles:
                                st.info(
                                    f"Found {len(articles)} article(s) (showing up to 50)"
                                )

                                for idx, (source, text, extra) in enumerate(
                                    articles, 1
                                ):
                                    try:
                                        extra_data = json.loads(extra) if extra else {}
                                        citation = format_citation(extra)

                                        if citation:
                                            st.markdown(f"{idx}. {citation}")
                                        else:
                                            title = extra_data.get(
                                                "display_name", source
                                            )
                                            st.markdown(f"{idx}. {title}")

                                        # Show source link
                                        st.caption(f"[{source}]({source})")

                                        if idx < len(articles):
                                            st.markdown("---")

                                    except Exception as e:
                                        st.caption(
                                            f"Error formatting article {idx}: {e!s}"
                                        )
                            else:
                                st.info(
                                    f"No articles found matching filter ID pattern: {filter_id}"
                                )
                        else:
                            st.warning("Could not parse filter expression")

                    except Exception as e:
                        st.error(f"Error loading articles: {e!s}")

            st.markdown("---")
    else:
        st.info("No saved queries yet")

    st.markdown("---")

    # Show directories being watched
    st.subheader("Watched Directories")

    directories = db.execute(
        "SELECT path, last_updated FROM directories ORDER BY last_updated DESC"
    ).fetchall()

    if directories:
        st.markdown(f"**{len(directories)} directories:**")
        for path, last_updated in directories:
            col1, col2 = st.columns([4, 1])
            with col1:
                st.text(f"{path}")
                st.caption(f"Last updated: {last_updated}")
            with col2:
                if st.button("Remove", key=f"remove_dir_{path}"):
                    db.execute("DELETE FROM directories WHERE path = ?", (path,))
                    db.commit()
                    st.rerun()
    else:
        st.info("No directories being watched")


def tag_counts(limit=10):
    """Return (tag, number of sources) for the LIMIT most used tags."""
    return db.execute(
        """SELECT t.tag, COUNT(*) as count
           FROM source_tag st
           JOIN tags t ON st.tag_id = t.rowid
           GROUP BY t.tag
           ORDER BY count DESC, t.tag
           LIMIT ?""",
        (limit,),
    ).fetchall()


def tab_stats_analytics():
    """Stats and analytics tab with visualizations."""
    st.title("📈 Stats & Analytics")

    nsources, db_size = get_db_stats()

    # Overview metrics
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Sources", nsources)
    with col2:
        st.metric("Database Size", f"{db_size:.2f} GB")
    with col3:
        tag_count = db.execute("SELECT COUNT(DISTINCT tag) FROM tags").fetchone()[0]
        st.metric("Unique Tags", tag_count)

    st.markdown("---")

    # Growth over time
    st.subheader("Library Growth")
    growth_data = db.execute(
        """SELECT date(date_added, 'start of month') as month,
           count(*) as new_sources
           FROM sources
           WHERE date_added IS NOT NULL
           GROUP BY month
           ORDER BY month DESC
           LIMIT 12"""
    ).fetchall()

    if growth_data:
        df = pd.DataFrame(growth_data, columns=["Month", "New Sources"])
        st.line_chart(df.set_index("Month"))
    else:
        st.info("No growth data available")

    st.markdown("---")

    # Top tags
    st.subheader("Most Used Tags")
    top_tags = tag_counts()

    if top_tags:
        df = pd.DataFrame(top_tags, columns=["Tag", "Count"])
        st.bar_chart(df.set_index("Tag"))
    else:
        st.info("No tag data available")


def source_title(source, extra):
    """Return a title for SOURCE from its EXTRA json (which may be None)."""
    try:
        data = json.loads(extra) if extra else {}
    except json.JSONDecodeError:
        data = {}
    return (data or {}).get("title") or (data or {}).get("display_name") or source


def export_rows(filter_option, tag=None, days=None):
    """Return the (source, extra) rows to export for FILTER_OPTION."""
    if filter_option == "By tag":
        return db.execute(
            """SELECT s.source, s.extra FROM sources s
               JOIN source_tag st ON s.rowid = st.source_id
               JOIN tags t ON st.tag_id = t.rowid
               WHERE t.tag = ? ORDER BY s.source""",
            (tag,),
        ).fetchall()
    if filter_option == "Recent":
        return db.execute(
            """SELECT source, extra FROM sources
               WHERE date_added > datetime('now', ?) ORDER BY date_added DESC""",
            (f"-{days} days",),
        ).fetchall()
    return db.execute("SELECT source, extra FROM sources ORDER BY source").fetchall()


def bibtex_entries(rows):
    """Return (bibtex, skipped) for the (source, extra) ROWS.

    Only works from OpenAlex have bibtex entries; the other sources are
    returned in skipped.
    """
    entries, skipped = [], []
    for source, extra in rows:
        try:
            bibtex = dump_bibtex(json.loads(extra)) if extra else None
        except Exception:
            bibtex = None
        if bibtex:
            entries.append(bibtex.strip())
        else:
            skipped.append(source)
    return "\n\n".join(entries), skipped


def citations(rows):
    """Return the citations of the (source, extra) ROWS, one per line."""
    lines = []
    for source, extra in rows:
        try:
            data = json.loads(extra) if extra else {}
        except json.JSONDecodeError:
            data = {}
        lines.append(
            (data or {}).get("citation")
            or (format_citation(extra) if data else None)
            or source
        )
    return "\n".join(lines)


def run_sql(sql):
    """Run SQL once, commit it, and return (columns, rows).

    columns is None for a statement that returns no rows.
    """
    cursor = db.execute(sql)
    rows = cursor.fetchall() or []
    db.commit()
    columns = [d[0] for d in cursor.description] if cursor.description else None
    return columns, rows


def tab_export():
    """Export tab for BibTeX, citations, etc."""
    st.title("📤 Export")

    export_format = st.selectbox(
        "Export Format", ["BibTeX", "Citations", "Summary Newsletter", "Raw SQL"]
    )

    if export_format in ("BibTeX", "Citations"):
        st.subheader(f"Export {export_format}")

        filter_option = st.selectbox("Filter by", ["All sources", "By tag", "Recent"])
        tag = days = None
        if filter_option == "By tag":
            tags = [
                t[0]
                for t in db.execute(
                    "SELECT DISTINCT tag FROM tags ORDER BY tag"
                ).fetchall()
            ]
            if not tags:
                st.info("No tags found in database")
                return
            tag = st.selectbox("Select Tag", tags)
        elif filter_option == "Recent":
            days = st.slider("From last N days", 1, 90, 7)

        if st.button(f"Generate {export_format}"):
            rows = export_rows(filter_option, tag, days)
            if not rows:
                st.info("No sources to export")
                return

            if export_format == "BibTeX":
                text, skipped = bibtex_entries(rows)
                st.success(f"{len(rows) - len(skipped)} BibTeX entries")
                if skipped:
                    st.caption(
                        f"{len(skipped)} sources without a bibtex entry "
                        "(files, web pages and other non-OpenAlex sources) were skipped."
                    )
                filename, language = "litdb.bib", "bibtex"
            else:
                text = citations(rows)
                st.success(f"{len(rows)} citations")
                filename, language = "litdb-citations.txt", "text"

            if text:
                st.download_button(
                    f"📥 Download {filename}", data=text, file_name=filename
                )
                st.code(text, language=language)

    elif export_format == "Summary Newsletter":
        st.subheader("Generate Summary Newsletter")

        with st.form("newsletter_form"):
            time_period = st.selectbox(
                "Time Period", ["1 week", "2 weeks", "1 month", "3 months"]
            )
            model = st.text_input("Model", value=gpt["model"])
            newsletter_submitted = st.form_submit_button("Generate Newsletter")

        if newsletter_submitted:
            import tempfile

            from litdb.summary import generate_summary

            try:
                with (
                    st.spinner(f"Generating newsletter for {time_period}..."),
                    tempfile.TemporaryDirectory() as d,
                ):
                    newsletter = generate_summary(
                        since=time_period,
                        output_file=os.path.join(d, "newsletter.org"),
                        model=model or None,
                    )
            except Exception as e:
                st.error(f"Failed to generate the newsletter: {e}")
                return

            if not newsletter:
                st.info(f"No articles to summarize in the last {time_period}.")
                return
            st.download_button(
                "📥 Download newsletter.org",
                data=newsletter,
                file_name="newsletter.org",
            )
            st.code(newsletter, language="org")

    elif export_format == "Raw SQL":
        st.subheader("Raw SQL Query")
        st.caption("Statements that change the database are committed.")

        with st.form("sql_form"):
            sql_query = st.text_area(
                "Enter SQL query", value="SELECT * FROM sources LIMIT 10", height=100
            )
            sql_submitted = st.form_submit_button("Execute Query")

        if sql_submitted:
            try:
                columns, results = run_sql(sql_query)
            except Exception as e:
                st.error(f"Query error: {e}")
                return
            if results:
                st.dataframe(pd.DataFrame(results, columns=columns))
            elif columns:
                st.info("Query returned no results")
            else:
                st.success("Statement executed")


def research_failed(error, hint=None):
    """Show the error step of the research tab with ERROR and HINT."""
    st.session_state.research_error = error
    st.session_state.research_hint = hint
    st.session_state.research_step = "error"
    st.rerun()


def tab_research():
    """Research tab for deep research queries with interactive refinement."""
    st.title("🔬 Research")

    st.markdown("""
    Run deep research queries using gpt_researcher or FutureHouse.
    For Deep Research, you can optionally refine your query before starting.
    """)

    # Initialize session state
    if "research_step" not in st.session_state:
        st.session_state.research_step = "input"
    if "research_query" not in st.session_state:
        st.session_state.research_query = ""
    if "research_type" not in st.session_state:
        st.session_state.research_type = "Deep Research (gpt_researcher)"
    if "report_type" not in st.session_state:
        st.session_state.report_type = "research_report"
    if "refinement_suggestions" not in st.session_state:
        st.session_state.refinement_suggestions = ""
    if "user_refinement" not in st.session_state:
        st.session_state.user_refinement = ""

    # Step 1: Input query and options
    if st.session_state.research_step == "input":
        with st.form("research_input_form"):
            research_type = st.selectbox(
                "Research Type",
                [
                    "Deep Research (gpt_researcher)",
                    "FutureHouse CROW",
                    "FutureHouse OWL",
                    "FutureHouse FALCON",
                ],
                index=[
                    "Deep Research (gpt_researcher)",
                    "FutureHouse CROW",
                    "FutureHouse OWL",
                    "FutureHouse FALCON",
                ].index(st.session_state.research_type),
            )

            query = st.text_area(
                "Research Query", value=st.session_state.research_query, height=100
            )

            report_type = "research_report"
            if research_type.startswith("Deep Research"):
                report_type = st.selectbox(
                    "Report Type",
                    ["research_report", "detailed_report", "resource_report"],
                    index=[
                        "research_report",
                        "detailed_report",
                        "resource_report",
                    ].index(st.session_state.report_type),
                )

                col1, col2 = st.columns(2)
                with col1:
                    refine_button = st.form_submit_button("Get Refinement Suggestions")
                with col2:
                    skip_refinement = st.form_submit_button("Start Research Directly")
            else:
                skip_refinement = st.form_submit_button("Start Research")
                refine_button = False

        if query:
            st.session_state.research_query = query
            st.session_state.research_type = research_type
            st.session_state.report_type = report_type

            if refine_button:
                # Get refinement suggestions
                st.session_state.research_step = "refining"
                st.rerun()
            elif skip_refinement:
                # Skip refinement, go straight to research
                st.session_state.research_step = "running"
                st.rerun()
        elif refine_button or skip_refinement:
            st.warning("Please enter a research query")

    # Step 2: Show refinement suggestions
    elif st.session_state.research_step == "refining":
        st.subheader("Query Refinement")

        if not st.session_state.refinement_suggestions:
            # Generate refinement suggestions
            with st.spinner("Analyzing your query..."):
                try:
                    from litdb.chat import get_completion

                    msgs = [
                        {
                            "role": "system",
                            "content": """You are an expert deep researcher.
Analyze this query to determine if any clarifying questions are needed to
help you provide a specific and focused response. If you need additional
information, let the user know and give them some examples of ways you could
focus the response and ask them what they would like.""",
                        },
                        {"role": "user", "content": st.session_state.research_query},
                    ]

                    suggestions = get_completion(gpt["model"], msgs)
                    st.session_state.refinement_suggestions = suggestions

                except Exception as e:
                    st.error(f"Failed to generate suggestions: {e}")
                    st.session_state.research_step = "input"
                    st.rerun()

        # Display original query
        st.markdown("**Original Query:**")
        st.info(st.session_state.research_query)

        # Display suggestions
        st.markdown("**Refinement Suggestions:**")
        st.markdown(st.session_state.refinement_suggestions)

        st.markdown("---")

        # Get user refinement
        refinement = st.text_area(
            "How would you like to refine the query? (Leave empty to use original query)",
            value=st.session_state.user_refinement,
            height=100,
            placeholder="e.g., 'Focus on papers from the last 5 years' or 'Include industrial applications'",
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Start Research with Refinement"):
                st.session_state.user_refinement = refinement
                st.session_state.research_step = "running"
                st.rerun()
        with col2:
            if st.button("Back to Query"):
                st.session_state.research_step = "input"
                st.session_state.refinement_suggestions = ""
                st.session_state.user_refinement = ""
                st.rerun()

    # Step 3: Run research
    elif st.session_state.research_step == "running":
        # Apply refinement if provided
        final_query = st.session_state.research_query

        if st.session_state.user_refinement:
            st.markdown("**Applying refinement...**")
            with st.spinner("Refining query..."):
                try:
                    from litdb.chat import get_completion

                    msgs = [
                        {
                            "role": "system",
                            "content": """Use the reply from the user to modify the original
                           prompt. You should only return the new prompt with no additional
                           explanation""",
                        },
                        {
                            "role": "user",
                            "content": f"<original_query>{st.session_state.research_query}</original_query>\n\n<refinement>{st.session_state.user_refinement}</refinement>",
                        },
                    ]

                    final_query = get_completion(gpt["model"], msgs)
                    st.success(f"**Refined Query:** {final_query}")

                except Exception as e:
                    st.warning(f"Failed to refine query: {e}. Using original query.")
                    final_query = st.session_state.research_query

        if st.session_state.research_type.startswith("Deep Research"):
            # Deep Research
            try:
                from litdb.research import deep_research

                st.info("**Running deep research...** This may take 2-10 minutes.")

                # Create progress indicators
                status_placeholder = st.empty()
                progress_bar = st.progress(0)

                status_placeholder.text("Initializing research...")
                progress_bar.progress(0.1)

                try:
                    status_placeholder.text("Running deep research...")
                    progress_bar.progress(0.3)

                    # Run research with skip_refinement=True since we handled it ourselves
                    report, result, context, costs, images, sources = deep_research(
                        final_query,
                        st.session_state.report_type,
                        verbose=False,
                        skip_refinement=True,  # We already handled refinement in the UI
                    )

                    progress_bar.progress(1.0)
                    status_placeholder.empty()
                    progress_bar.empty()

                    # Store results in session state
                    st.session_state.research_report = report
                    st.session_state.research_result = result
                    st.session_state.research_context = context
                    st.session_state.research_costs = costs
                    st.session_state.research_images = images
                    st.session_state.research_sources = sources
                    st.session_state.research_step = "results"
                    st.rerun()

                except Exception:
                    status_placeholder.empty()
                    progress_bar.empty()
                    raise

            except ImportError:
                research_failed(
                    "Deep research requires gpt_researcher to be installed",
                    "Install with: `pip install litdb[research]`",
                )
            except Exception as e:
                research_failed(f"Research failed: {e}")

        else:
            # FutureHouse research
            try:
                from futurehouse_client import FutureHouseClient, JobNames

                if "FUTURE_HOUSE_API_KEY" not in os.environ:
                    research_failed(
                        "FUTURE_HOUSE_API_KEY environment variable not set",
                        "Get an API key from https://platform.futurehouse.org/",
                    )
                else:
                    client = FutureHouseClient(
                        api_key=os.environ["FUTURE_HOUSE_API_KEY"]
                    )

                    jobs = {
                        "FutureHouse CROW": JobNames.CROW,
                        "FutureHouse OWL": JobNames.OWL,
                        "FutureHouse FALCON": JobNames.FALCON,
                    }

                    with st.spinner(
                        "Running FutureHouse research... This may take 2-10 minutes."
                    ):
                        # Create the task
                        import time

                        task_response = client.create_task(
                            {
                                "name": jobs[st.session_state.research_type],
                                "query": final_query,
                            }
                        )

                        task_id = task_response.task_id

                        # Poll until complete
                        while True:
                            result = client.get_task(task_id=str(task_id))
                            if result.status in ["completed", "failed", "error"]:
                                break
                            time.sleep(5)  # Wait 5 seconds between polls

                    # Store results
                    if result.status == "completed":
                        st.session_state.research_report = result.formatted_answer
                        st.session_state.research_step = "results"
                        st.rerun()
                    else:
                        research_failed(f"Task failed with status: {result.status}")

            except ImportError:
                research_failed(
                    "FutureHouse research requires futurehouse_client",
                    "Install with: `pip install litdb[futurehouse]`",
                )
            except Exception as e:
                research_failed(f"Research failed: {e}")

    # A failed run. This is its own step, so that clicking "Back to Input"
    # does not rerun the research, as it did when the button was shown in the
    # running step.
    elif st.session_state.research_step == "error":
        st.error(st.session_state.get("research_error", "Research failed"))
        if hint := st.session_state.get("research_hint"):
            st.info(hint)
        if st.button("Back to Input"):
            st.session_state.research_step = "input"
            st.rerun()

    # Step 4: Display results
    elif st.session_state.research_step == "results":
        st.success("Research complete!")

        # Display the report
        st.markdown("## Research Report")
        st.markdown(st.session_state.research_report)

        # Show additional info for Deep Research
        if st.session_state.research_type.startswith("Deep Research"):
            # Show costs
            with st.expander("Research Costs"):
                st.write(f"${st.session_state.research_costs}")

            # Show context
            if st.session_state.research_context:
                with st.expander("Context Used"):
                    st.markdown(st.session_state.research_context)

            # Show sources
            if st.session_state.research_sources:
                with st.expander("Sources"):
                    for i, source in enumerate(st.session_state.research_sources, 1):
                        st.write(f"{i}. {source}")

        # New research button
        if st.button("New Research"):
            # Clear session state
            st.session_state.research_step = "input"
            st.session_state.research_query = ""
            st.session_state.refinement_suggestions = ""
            st.session_state.user_refinement = ""
            st.rerun()


def tab_nsf_coa():
    """NSF COA (Collaborators and Other Affiliations) generator tab."""
    st.title("📋 NSF Collaborators and Other Affiliations (COA)")

    st.markdown("""
    Generate Table 4 for NSF COA using your ORCID. This will retrieve your publications
    from the last 4 years and create an Excel file with all co-authors and their affiliations.
    """)

    # ORCID input
    with st.form("nsf_coa_form"):
        orcid_input = st.text_input(
            "ORCID",
            placeholder="e.g., 0000-0003-2625-9232 or https://orcid.org/0000-0003-2625-9232",
            help="Enter your ORCID identifier",
        )

        email_input = st.text_input(
            "Email (optional)",
            placeholder="your.email@example.com",
            help="Optional: Provide your email for OpenAlex API polite pool (faster response)",
        )

        submitted = st.form_submit_button("Generate COA")

    if submitted and orcid_input:
        with st.spinner(
            "Generating COA... This may take a few minutes depending on publication count."
        ):
            try:
                from litdb.coa import get_coa

                # get_coa saves the file in ~/Downloads and returns its path.
                file_path = get_coa(orcid_input, email=email_input or None)

                if file_path and os.path.exists(file_path):
                    with open(file_path, "rb") as f:
                        file_data = f.read()

                    st.success(f"✓ COA generated successfully! Saved to {file_path}")

                    st.download_button(
                        label="📥 Download COA Excel File",
                        data=file_data,
                        file_name=os.path.basename(file_path),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )

                    df = pd.read_excel(file_path, sheet_name="Table 4")

                    st.markdown("---")
                    st.subheader("Summary")
                    st.info(
                        f"Found **{len(df)}** unique co-authors from your publications in the last 4 years."
                    )

                    with st.expander("Preview Table 4 (first 10 rows)"):
                        st.dataframe(df.head(10))

                else:
                    st.error("Failed to generate COA file")

            except Exception as e:
                error_msg = str(e)
                if "Unexpected API response" in error_msg:
                    st.error("❌ OpenAlex API error. Please check:")
                    st.markdown("""
                    - Is the ORCID correct?
                    - Does the ORCID have publications in OpenAlex?
                    - Try again in a few moments (API may be temporarily unavailable)
                    """)
                elif "KeyError" in error_msg:
                    st.error(
                        "❌ API response format error. The OpenAlex API may have changed or is returning unexpected data."
                    )
                else:
                    st.error(f"❌ Error generating COA: {error_msg}")

                import traceback

                with st.expander("Show technical error details"):
                    st.code(traceback.format_exc())

    elif submitted and not orcid_input:
        st.warning("Please enter an ORCID")


def main():
    """Main application entry point."""
    # Get version from package metadata
    try:
        from importlib.metadata import version

        litdb_version = version("litdb")
    except Exception:
        litdb_version = "unknown"

    st.set_page_config(
        page_title=f"LitDB v{litdb_version}",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Render sidebar and get selected tab
    selected_tab = render_sidebar()

    # Route to appropriate tab
    if selected_tab == "🔍 Search":
        tab_search()
    elif selected_tab == "🔎 OpenAlex Search":
        tab_openalex_search()
    elif selected_tab == "📖 Semantic Scholar Search":
        tab_semantic_scholar_search()
    elif selected_tab == "👥 Suggest Reviewers":
        tab_suggest_reviewers()
    elif selected_tab == "💬 Chat":
        tab_chat()
    elif selected_tab == "➕ Add Content":
        tab_add_content()
    elif selected_tab == "📚 Library Browser":
        tab_library_browser()
    elif selected_tab == "⚙️ Manage Filters":
        tab_manage_filters()
    elif selected_tab == "📈 Stats & Analytics":
        tab_stats_analytics()
    elif selected_tab == "📤 Export":
        tab_export()
    elif selected_tab == "🔬 Research":
        tab_research()
    elif selected_tab == "📋 NSF COA":
        tab_nsf_coa()


if __name__ == "__main__":
    main()
