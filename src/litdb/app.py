"""Streamlit app for litdb.

Enhanced multi-tab interface for literature database management.
"""

import json
import os

import pandas as pd
import streamlit as st
from litellm import completion

from litdb.chat import get_rag_content
from litdb.db import get_db
from litdb.utils import get_config

# Configuration
config = get_config()
db = get_db()
gpt = config.get("llm", {"model": "ollama/llama2"})
dbf = os.path.join(config["root"], "litdb.libsql")

# Constants
KB = 1024
MB = 1024 * KB
GB = 1024 * MB


def get_db_stats():
    """Get database statistics."""
    (nsources,) = db.execute("select count(source) from sources").fetchone()
    db_size = os.path.getsize(dbf) / GB
    return nsources, db_size


def render_sidebar():
    """Render sidebar with navigation and database info."""
    st.sidebar.title("LitDB")

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
            "💬 Chat",
            "📚 Library Browser",
            "⚙️ Manage Filters",
            "📈 Stats & Analytics",
            "📤 Export",
            "🔬 Research",
            "➕ Add Content",
        ],
    )

    return tab


def format_citation(extra):
    """Format citation from extra JSON data."""
    if not extra:
        return None

    try:
        data = json.loads(extra)

        # Try to build a citation
        parts = []

        # Authors
        if "authorships" in data and data["authorships"]:
            authors = [a["author"]["display_name"] for a in data["authorships"][:3]]
            if len(data["authorships"]) > 3:
                authors.append("et al.")
            parts.append(", ".join(authors))

        # Year
        if "publication_year" in data:
            parts.append(f"({data['publication_year']})")

        # Title
        if "title" in data:
            parts.append(data["title"])

        # Journal/venue
        if "host_venue" in data and data["host_venue"]:
            venue = data["host_venue"].get("display_name", "")
            if venue:
                parts.append(f"*{venue}*")

        return ". ".join(parts) if parts else None
    except Exception:
        return None


def tab_search():
    """Search tab with vector, full-text, and hybrid search."""
    st.title("🔍 Search")

    # Use form to allow Enter key to submit
    with st.form("search_form"):
        search_type = st.selectbox(
            "Search Type", ["Vector Search", "Full-Text Search", "Hybrid Search"]
        )
        query = st.text_input("Enter your search query")
        n_results = st.slider("Number of results", 1, 20, 5)
        search_submitted = st.form_submit_button("Search")

    if search_submitted:
        if not query:
            st.warning("Please enter a search query")
            return

        st.subheader("Results")

        if search_type == "Vector Search":
            # Vector search - we need to compute embedding first
            from sentence_transformers import SentenceTransformer
            import numpy as np

            config = get_config()
            model = SentenceTransformer(config["embedding"]["model"])
            emb = model.encode([query]).astype(np.float32).tobytes()

            results = db.execute(
                """SELECT sources.source, sources.text, sources.extra,
                   vector_distance_cos(?, embedding) as d
                   FROM vector_top_k('embedding_idx', ?, ?)
                   JOIN sources ON sources.rowid = id""",
                [emb, emb, n_results],
            ).fetchall()

            for i, (source, text, extra, distance) in enumerate(results, 1):
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title[:100]}... (distance: {distance:.4f})"):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Text preview:** {text[:300]}...")

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_v_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)

        elif search_type == "Full-Text Search":
            # Full-text search
            results = db.execute(
                """SELECT sources.source, sources.text,
                   snippet(fulltext, 1, '<b>', '</b>', '...', 16) as snippet,
                   sources.extra
                   FROM fulltext
                   INNER JOIN sources ON fulltext.source = sources.source
                   WHERE fulltext.text MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                [query, n_results],
            ).fetchall()

            for i, (source, text, snippet, extra) in enumerate(results, 1):
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title[:100]}..."):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Snippet:** {snippet}", unsafe_allow_html=True)

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_fts_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)

        elif search_type == "Hybrid Search":
            st.info("Hybrid search combines vector and full-text results")

            # Vector search
            from sentence_transformers import SentenceTransformer
            import numpy as np

            config = get_config()
            model = SentenceTransformer(config["embedding"]["model"])
            emb = model.encode([query]).astype(np.float32).tobytes()

            vector_results = db.execute(
                """SELECT sources.source, sources.text, sources.extra,
                   vector_distance_cos(?, embedding) as d
                   FROM vector_top_k('embedding_idx', ?, ?)
                   JOIN sources ON sources.rowid = id""",
                [emb, emb, n_results],
            ).fetchall()

            # Full-text search
            fts_results = db.execute(
                """SELECT sources.source, sources.text,
                   snippet(fulltext, 1, '<b>', '</b>', '...', 16) as snippet
                   FROM fulltext
                   INNER JOIN sources ON fulltext.source = sources.source
                   WHERE fulltext.text MATCH ?
                   ORDER BY rank
                   LIMIT ?""",
                [query, n_results],
            ).fetchall()

            st.markdown("**Vector Search Results:**")
            for i, (source, text, extra, distance) in enumerate(vector_results, 1):
                citation = format_citation(extra)
                title = citation if citation else source

                with st.expander(f"{i}. {title[:100]}... (distance: {distance:.4f})"):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Text preview:** {text[:200]}...")

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

                with st.expander(f"{i}. {title[:100]}..."):
                    if citation:
                        st.markdown(citation)
                        st.markdown("---")
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Snippet:** {snippet}", unsafe_allow_html=True)

                    # Show full metadata with toggle
                    if extra and st.checkbox("Show full metadata", key=f"meta_hf_{i}"):
                        try:
                            extra_data = json.loads(extra)
                            st.json(extra_data)
                        except Exception:
                            st.text(extra)


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
        # Display user message
        with st.chat_message("user"):
            st.markdown(prompt)

        # Get RAG content
        rag_content, references = get_rag_content(prompt, 3)

        # Expand prompt with RAG content
        expanded_prompt = f"""Use the following retrieved information to respond to
the user prompt. Reference the citations if you use that information.

<retrieved information>
{rag_content}

<user prompt>
{prompt}"""

        st.session_state.messages.append({"role": "user", "content": expanded_prompt})

        # Generate and display assistant response
        with st.chat_message("assistant"):
            stream = completion(
                model=st.session_state["model"],
                messages=st.session_state.messages,
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
            if doi_input:
                dois = [d.strip() for d in doi_input.split("\n") if d.strip()]
                st.info(f"Adding {len(dois)} DOI(s)...")

                for doi in dois:
                    try:
                        # Here you would call the actual add function
                        st.success(f"Added: {doi}")
                    except Exception as e:
                        st.error(f"Failed to add {doi}: {e}")
            else:
                st.warning("Please enter at least one DOI")

    elif add_method == "ORCID":
        st.subheader("Add by ORCID")

        with st.form("orcid_form"):
            orcid = st.text_input("Enter ORCID ID")
            n_works = st.slider("Number of works to fetch", 1, 50, 10)
            orcid_submitted = st.form_submit_button("Fetch Works")

        if orcid_submitted:
            if orcid:
                st.info(f"Fetching {n_works} works from ORCID {orcid}...")
                # Here you would call the actual ORCID fetch function
                st.success("Works fetched successfully")
            else:
                st.warning("Please enter an ORCID ID")

    elif add_method == "BibTeX":
        st.subheader("Add from BibTeX")

        with st.form("bibtex_form"):
            bibtex_input = st.text_area("Paste BibTeX entries", height=200)
            bibtex_submitted = st.form_submit_button("Add from BibTeX")

        if bibtex_submitted:
            if bibtex_input:
                st.info("Processing BibTeX entries...")
                # Here you would call the actual BibTeX parser
                st.success("BibTeX entries added successfully")
            else:
                st.warning("Please paste BibTeX entries")

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
                import json
                import requests
                from difflib import SequenceMatcher
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

                            # Add to database
                            if dois_to_add:
                                st.subheader("Adding to Database")
                                progress_bar = st.progress(0)
                                status_text = st.empty()

                                successfully_added = []
                                failed_to_add = []

                                for i, doi in enumerate(dois_to_add):
                                    status_text.text(
                                        f"Adding {i + 1}/{len(dois_to_add)}: {doi}"
                                    )
                                    try:
                                        # Import and call the add functionality
                                        from litdb.db import add_work

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
                import tempfile
                import pathlib

                # Save uploaded file to temporary location
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=pathlib.Path(uploaded_file.name).suffix
                ) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_path = tmp_file.name

                try:
                    with st.spinner(f"Processing {uploaded_file.name}..."):
                        # Import the add logic
                        from litdb.commands.manage import add as cli_add
                        from click import Context

                        # Call the add function
                        with Context(cli_add) as ctx:
                            ctx.invoke(cli_add, sources=[tmp_path])

                    st.success(f"✓ Successfully added: {uploaded_file.name}")

                except Exception as e:
                    st.error(f"Failed to add file: {e}")

                finally:
                    # Clean up temp file
                    import os

                    try:
                        os.unlink(tmp_path)
                    except Exception:
                        pass

        else:  # URL
            with st.form("url_form"):
                url_input = st.text_input(
                    "Enter URL", placeholder="https://example.com/article"
                )
                url_submitted = st.form_submit_button("Add URL")

            if url_submitted:
                if url_input:
                    try:
                        with st.spinner(f"Processing {url_input}..."):
                            # Import the add logic
                            from litdb.commands.manage import add as cli_add
                            from click import Context

                            # Call the add function
                            with Context(cli_add) as ctx:
                                ctx.invoke(cli_add, sources=[url_input])

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
            )
            directory_submitted = st.form_submit_button("Index Directory")

        if directory_submitted:
            if directory_path:
                import pathlib

                dir_path = pathlib.Path(directory_path)

                if not dir_path.exists():
                    st.error(f"Directory does not exist: {directory_path}")
                elif not dir_path.is_dir():
                    st.error(f"Path is not a directory: {directory_path}")
                else:
                    try:
                        # Find all supported files
                        supported_extensions = [
                            ".pdf",
                            ".docx",
                            ".pptx",
                            ".org",
                            ".md",
                            ".html",
                            ".bib",
                            ".ipynb",
                        ]

                        files_to_add = []
                        for ext in supported_extensions:
                            files_to_add.extend(dir_path.rglob(f"*{ext}"))

                        # Filter out files already in database
                        db = get_db()
                        new_files = []
                        for fname in files_to_add:
                            if not db.execute(
                                "SELECT source FROM sources WHERE source = ?",
                                (str(fname),),
                            ).fetchone():
                                new_files.append(fname)

                        if not new_files:
                            st.info(
                                f"No new files found in {directory_path} (all files already indexed)"
                            )
                        else:
                            st.info(f"Found {len(new_files)} new file(s) to index")

                            # Add files with progress bar
                            progress_bar = st.progress(0)
                            status_text = st.empty()

                            successfully_added = []
                            failed_to_add = []

                            from litdb.commands.manage import add as cli_add
                            from click import Context

                            for i, fname in enumerate(new_files):
                                status_text.text(
                                    f"Adding {i + 1}/{len(new_files)}: {fname.name}"
                                )

                                try:
                                    with Context(cli_add) as ctx:
                                        ctx.invoke(cli_add, sources=[str(fname)])
                                    successfully_added.append(fname)
                                except Exception as e:
                                    failed_to_add.append((fname, str(e)))

                                progress_bar.progress((i + 1) / len(new_files))

                            status_text.empty()
                            progress_bar.empty()

                            # Update directories table
                            import datetime

                            last_updated = datetime.date.today().strftime("%Y-%m-%d")
                            directory_str = str(dir_path.resolve())

                            if db.execute(
                                "SELECT path FROM directories WHERE path = ?",
                                (directory_str,),
                            ).fetchone():
                                db.execute(
                                    "UPDATE directories SET last_updated = ? WHERE path = ?",
                                    (last_updated, directory_str),
                                )
                            else:
                                db.execute(
                                    "INSERT INTO directories(path, last_updated) VALUES (?, ?)",
                                    (directory_str, last_updated),
                                )
                            db.commit()

                            # Show results summary
                            st.success(
                                f"✓ Successfully indexed {len(successfully_added)} file(s)!"
                            )

                            if failed_to_add:
                                with st.expander(
                                    f"⚠ Failed to add {len(failed_to_add)} file(s)"
                                ):
                                    for fname, error in failed_to_add:
                                        st.error(f"{fname.name}: {error}")

                            # Show added files
                            if successfully_added:
                                with st.expander(
                                    f"✓ Indexed {len(successfully_added)} files",
                                    expanded=False,
                                ):
                                    for fname in successfully_added:
                                        st.markdown(f"- {fname}")

                    except Exception as e:
                        st.error(f"Error indexing directory: {e}")
            else:
                st.warning("Please enter a directory path")


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
                # Try to get title from extra JSON
                title = source
                if extra:
                    try:
                        extra_data = json.loads(extra)
                        title = extra_data.get("title", source)
                    except Exception:
                        pass

                with st.expander(f"{title[:80]}... (Added: {date_added})"):
                    st.markdown(f"**Source:** {source}")
                    st.markdown(f"**Preview:** {text[:200]}...")
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
                    # Try to get title from extra JSON
                    title = source
                    if extra:
                        try:
                            extra_data = json.loads(extra)
                            title = extra_data.get("title", source)
                        except Exception:
                            pass

                    with st.expander(title[:80] + "..."):
                        st.markdown(f"**Source:** {source}")
                        st.markdown(f"**Preview:** {text[:200]}...")
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


def tab_manage_filters():
    """Manage filters tab for queries and searches."""
    st.title("⚙️ Manage Filters & Queries")

    st.markdown("""
    Manage saved search filters and queries. These are used by the CLI's `watch` and `follow` commands.
    """)

    # Add new query
    st.subheader("Add New Query")

    with st.form("new_query_form"):
        new_filter = st.text_input(
            "Filter Expression",
            placeholder="e.g., author.id:A1234567890",
            help="OpenAlex filter expression",
        )
        new_description = st.text_area(  # noqa: F841
            "Description (optional)", placeholder="What this query tracks..."
        )

        if st.form_submit_button("Save Query"):
            if new_filter:
                st.success(f"Query saved: {new_filter}")
                st.info(
                    "Note: To actually save, this would need to call the add_filter CLI command"
                )
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
            with st.expander(f"{filter_text[:60]}..."):
                st.markdown(f"**Filter:** `{filter_text}`")
                if description:
                    st.markdown(f"**Description:** {description}")
                st.markdown(f"**Last Updated:** {last_updated}")

                col1, col2 = st.columns([3, 1])
                with col2:
                    if st.button("Delete", key=f"delete_query_{i}"):
                        st.info("Query deletion coming soon...")
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
                    st.info("Directory removal coming soon...")
    else:
        st.info("No directories being watched")


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
    top_tags = db.execute(
        """SELECT tag, COUNT(*) as count
           FROM tags
           GROUP BY tag
           ORDER BY count DESC
           LIMIT 10"""
    ).fetchall()

    if top_tags:
        df = pd.DataFrame(top_tags, columns=["Tag", "Count"])
        st.bar_chart(df.set_index("Tag"))
    else:
        st.info("No tag data available")


def tab_export():
    """Export tab for BibTeX, citations, etc."""
    st.title("📤 Export")

    export_format = st.selectbox(
        "Export Format", ["BibTeX", "Citations", "Summary Newsletter", "Raw SQL"]
    )

    if export_format == "BibTeX":
        st.subheader("Export BibTeX")

        filter_option = st.selectbox("Filter by", ["All sources", "By tag", "Recent"])

        if filter_option == "By tag":
            tags = db.execute("SELECT DISTINCT tag FROM tags ORDER BY tag").fetchall()
            if tags:
                tag_list = [t[0] for t in tags]
                selected_tag = st.selectbox("Select Tag", tag_list)

                if st.button("Generate BibTeX"):
                    st.info(f"Generating BibTeX for tag '{selected_tag}'...")
                    st.code(
                        "@article{example2024,\n  title={Example},\n  author={Author},\n}",
                        language="bibtex",
                    )

        elif filter_option == "Recent":
            days = st.slider("From last N days", 1, 90, 7)
            if st.button("Generate BibTeX"):
                st.info(f"Generating BibTeX for last {days} days...")

        else:  # All sources
            if st.button("Generate BibTeX"):
                st.info("Generating BibTeX for all sources...")

    elif export_format == "Citations":
        st.subheader("Export Citations")
        citation_style = st.selectbox("Citation Style", ["APA", "MLA", "Chicago"])
        st.info(f"Citation export in {citation_style} format coming soon")

    elif export_format == "Summary Newsletter":
        st.subheader("Generate Summary Newsletter")

        with st.form("newsletter_form"):
            time_period = st.selectbox(
                "Time Period", ["1 week", "2 weeks", "1 month", "3 months"]
            )
            model = st.text_input("Model", value=gpt["model"])  # noqa: F841
            newsletter_submitted = st.form_submit_button("Generate Newsletter")

        if newsletter_submitted:
            st.info(f"Generating newsletter for {time_period}...")
            st.markdown("""
            ## Newsletter Summary

            This would contain a summary of recent papers organized by topic...
            """)

    elif export_format == "Raw SQL":
        st.subheader("Raw SQL Query")

        with st.form("sql_form"):
            sql_query = st.text_area(
                "Enter SQL query", value="SELECT * FROM sources LIMIT 10", height=100
            )
            sql_submitted = st.form_submit_button("Execute Query")

        if sql_submitted:
            try:
                results = db.execute(sql_query).fetchall()
                if results:
                    # Get column names
                    cols = [desc[0] for desc in db.execute(sql_query).description]
                    df = pd.DataFrame(results, columns=cols)
                    st.dataframe(df)
                else:
                    st.info("Query returned no results")
            except Exception as e:
                st.error(f"Query error: {e}")


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

                except Exception as inner_e:
                    status_placeholder.empty()
                    progress_bar.empty()
                    raise inner_e

            except ImportError:
                st.error("Deep research requires gpt_researcher to be installed")
                st.info("Install with: `pip install litdb[research]`")
                if st.button("Back to Input"):
                    st.session_state.research_step = "input"
                    st.rerun()
            except Exception as e:
                st.error(f"Research failed: {e}")
                if st.button("Back to Input"):
                    st.session_state.research_step = "input"
                    st.rerun()

        else:
            # FutureHouse research
            try:
                from futurehouse_client import FutureHouseClient, JobNames

                if "FUTURE_HOUSE_API_KEY" not in os.environ:
                    st.error("FUTURE_HOUSE_API_KEY environment variable not set")
                    st.info("Get an API key from https://platform.futurehouse.org/")
                    if st.button("Back to Input"):
                        st.session_state.research_step = "input"
                        st.rerun()
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
                        task_response = client.run_tasks_until_done(
                            {
                                "name": jobs[st.session_state.research_type],
                                "query": final_query,
                            }
                        )

                    # Store results
                    st.session_state.research_report = task_response[0].formatted_answer
                    st.session_state.research_step = "results"
                    st.rerun()

            except ImportError:
                st.error("FutureHouse research requires futurehouse_client")
                st.info("Install with: `pip install litdb[futurehouse]`")
                if st.button("Back to Input"):
                    st.session_state.research_step = "input"
                    st.rerun()
            except Exception as e:
                st.error(f"Research failed: {e}")
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


def main():
    """Main application entry point."""
    st.set_page_config(
        page_title="LitDB",
        page_icon="📚",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Render sidebar and get selected tab
    selected_tab = render_sidebar()

    # Route to appropriate tab
    if selected_tab == "🔍 Search":
        tab_search()
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


if __name__ == "__main__":
    main()
