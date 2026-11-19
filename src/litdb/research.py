"""Deep research for litdb.

This is mostly a wrapper around gpt_researcher with the following additions:

1. The initial query is refined before proceeding.
2. A vector search is used to provide related content from litdb
3. A full-text search is used to provide related content from litdb
4. OpenAlex queries are used to provide related content

The whole thing is wrapped into the litdb cli for convenience.

TODO:
1. Store results in litdb. This mitigates the need to remember to store the
results in an output file. It would also enable you to continue doing research
that builds on itself. This needs some kind of tag / label capability to enable
you to bring up related items to continue.

2. Wrap the research function in a loop so a chat stays alive and you can
continue it.
"""

import asyncio
import json
import os

import numpy as np
from langchain_core.documents import Document
from litellm import completion

from .db import get_db, get_model
from .openalex import get_data, get_text
from .utils import extract_json, get_config


def research_env():
    """Set up the environment variables.

    Use litdb.toml to specify the models used.

    Some other env vars determine what retrievers are used if they are defined.

    NCBI_API_KEY  ->  pubmed_central
    GOOGLE_CX_KEY -> google
    TAVILY_API_KEY -> tavily

    Others from gpt_researcher could be supported, but I haven't used them
    myself.
    """
    config = get_config()
    gr_config = config.get("gpt-researcher", {})

    def setting(name, default):
        """Use litdb.toml, then the environment, then DEFAULT for NAME."""
        os.environ[name] = gr_config.get(name, os.environ.get(name, default))

    # You won't always need this, but it is harmless to set here.
    setting("OLLAMA_BASE_URL", "http://localhost:11434")

    # see https://docs.gptr.dev/docs/gpt-researcher/llms/llms for examples
    setting("FAST_LLM", "ollama:llama3.3")
    setting("SMART_LLM", "ollama:llama3.3")
    setting("STRATEGIC_LLM", "ollama:llama3.3")
    setting("EMBEDDING", "ollama:nomic-embed-text")

    # Where to get data
    retrievers = "arxiv"

    # API keys
    if "NCBI_API_KEY" in os.environ:
        print("Adding pubmed search")
        retrievers += ",pubmed_central"

    if "GOOGLE_CX_KEY" in os.environ:
        print("Adding google search")
        retrievers += ",google"

    if "TAVILY_API_KEY" in os.environ:
        print("Adding Tavily")
        retrievers += ",tavily"

    setting("RETRIEVER", retrievers)


def oa_query(query):
    """Get data from OpenAlex for query."""
    config = get_config()
    url = "https://api.openalex.org/works"

    # The search parameter, unlike a filter, allows commas in the query.
    params = {
        "search": query,
        "mailto": config["openalex"].get("email"),
        "api_key": config["openalex"].get("api_key"),
    }

    d = get_data(url, params)

    return d


def litdb_documents(query):
    """Create the litdb documents.

    Query should be a string.

    Returns a list of langchain Documents.
    """
    config = get_config()
    db = get_db()
    model = get_model(config["embedding"]["model"])
    emb = model.encode([query]).astype(np.float32).tobytes()

    # number of queries to return or generate. This is used in several places. I
    # don't think it makes sense to configure each one independently. We default
    # to 5.
    n_queries = config.get("gpt-researcher", {}).get("n_queries", 5)

    # vector search
    results = db.execute(
        """select
            sources.source, sources.text,
            sources.extra, vector_distance_cos(?, embedding) as d
            from vector_top_k('embedding_idx', ?, ?)
            join sources on sources.rowid = id
            order by d""",
        (emb, emb, n_queries),
    ).fetchall()

    documents = []

    for i, (source, text, extra, d) in enumerate(results):
        documents += [
            Document(
                page_content=text,
                metadata={"source": source, "type": "vector search", "query": query},
            )
        ]

    # Full text search in the litdb - Ideally I would use litellm for enforcing
    # json, but not all models support that, notably gemini doesn't seem to
    # support it, and I use that one a lot.
    msgs = [
        {
            "role": "system",
            "content": f"""You are an expert deep researcher that outputs only
valid JSON. Analyze this query to identify full text queries that could be
relevant. The queries will be used with sqlite fts5.

             Return a list of {n_queries} queries in json:

             {{"queries": [query1, query2, ...]}}

             Respond with a JSON object, without backticks or markdown
             formatting.""",
        },
        {"role": "user", "content": query},
    ]

    model = config.get("llm", {}).get("model", "ollama/llama3.3")
    response = completion(model=model, messages=msgs)

    content = response["choices"][0]["message"]["content"] or ""
    try:
        queries = json.loads(extract_json(content))["queries"]
        if not isinstance(queries, list):
            raise TypeError("queries is not a list")
        queries = [str(q) for q in queries]
    except (ValueError, KeyError, TypeError) as e:
        print(f"Generating full text queries failed ({e}) on:")
        print(content)
        print("Proceeding without full text queries.")
        queries = []

    for q in queries:
        results = _fulltext_search(db, q, n_queries)

        for j, (source, text, snippet, extra, score) in enumerate(results):
            documents += [
                Document(
                    page_content=text,
                    metadata={"source": source, "type": "full-text", "query": q},
                )
            ]

        # OpenAlex queries
        oa = oa_query(q)
        for j, result in enumerate(oa["results"][0:n_queries]):
            documents += [
                Document(
                    page_content=get_text(result),
                    metadata={"source": result["id"], "type": "openalex", "query": q},
                )
            ]

    return documents


def _fts_literal(query):
    """Quote each word of QUERY so FTS5 matches it literally."""
    return " ".join('"' + w.replace('"', '""') + '"' for w in query.split())


def _fulltext_search(db, query, n):
    """Return up to N full-text matches for QUERY.

    QUERY is used as FTS5 syntax (the LLM is asked for FTS5 queries), and if it
    is not valid FTS5, as a list of words.
    """
    sql = """select
        sources.source, sources.text, snippet(fulltext, 1, '', '', '', 16),
        sources.extra, bm25(fulltext)
        from fulltext
        inner join sources on fulltext.source = sources.source
        where fulltext.text match ? order by rank limit ?"""
    for q in (query, _fts_literal(query)):
        try:
            return db.execute(sql, (q, n)).fetchall()
        except ValueError:
            continue
    return []


def refine_query(query):
    """Refine the query.

    The goal is to ask some clarifying questions about the query, and then
    refine it to get a better starting point for research.
    """
    config = get_config()
    msgs = [
        {
            "role": "system",
            "content": """You are an expert deep researcher.
Analyze this query to determine if any clarifying questions are needed to
help you provide a specific and focused response. If you need additional
information, let the user know and give them some examples of ways you could
focus the response and ask them what they would like.""",
        },
        {"role": "user", "content": query},
    ]

    # This might ideally be FAST_LLM, but it is not in litellm form
    model = config.get("llm", {}).get("model", "ollama/llama3.3")

    response = completion(model=model, messages=msgs, stream=True)
    output = ""
    for chunk in response:
        out = chunk.choices[0].delta.content or ""
        print(out, end="")
        output += out

    print()
    reply = input("Enter for no change > ")

    if reply.strip():
        # Now get the user response. The model needs its own questions to make
        # sense of the reply.
        msgs += [
            {"role": "assistant", "content": output},
            {
                "role": "system",
                "content": """Use the reply from the user to modify the original
               prompt. You should only return the new prompt with no additional
               explanation""",
            },
            {
                "role": "user",
                "content": f"<reply>{reply}</reply>",
            },
        ]

        response = completion(model=model, messages=msgs, stream=True)

        print("New query: ")
        output = ""
        for chunk in response:
            out = chunk.choices[0].delta.content or ""
            print(out, end="")
            output += out
        print()

        query = output.strip() or query

    print(f"Doing research on:\n\n{query}\n\n")

    return query


# Where the research material comes from. "litdb" uses documents from your
# litdb (vector and full-text search) and from OpenAlex. The others are
# gpt_researcher's own: web retrievers, local files in DOC_PATH, or both.
REPORT_SOURCES = {
    "litdb": "langchain_documents",
    "web": "web",
    "local": "local",
    "hybrid": "hybrid",
}


async def get_report(
    query: str,
    report_type: str,
    verbose: bool,
    skip_refinement: bool = False,
    source: str = "litdb",
):
    """Generate the report.

    QUERY: string to query and generate a report for.
    skip_refinement: if True, skip the interactive query refinement step
    source: a key of REPORT_SOURCES.

    Adapted from https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package.
    """
    # Import gpt_researcher here (it's an optional dependency in the research extra)
    from gpt_researcher import GPTResearcher

    research_env()
    if not skip_refinement:
        query = refine_query(query)
    else:
        print(f"Doing research on:\n\n{query}\n\n")

    # gpt_researcher only reads documents when report_source is
    # langchain_documents; with any other source they would be ignored.
    docs = litdb_documents(query) if source == "litdb" else None

    researcher = GPTResearcher(
        query=query,
        report_type=report_type,
        report_source=REPORT_SOURCES[source],
        verbose=verbose,
        documents=docs,
    )

    if verbose:
        c = researcher.cfg
        print(f"""CONFIG:
        retrievers:    {c.retrievers}

        fast_llm:      {c.fast_llm}
        smart_llm:     {c.smart_llm}
        strategic_llm: {c.strategic_llm}
        embedding:     {c.embedding}

        ndocs:         {len(researcher.documents)}
        doc_path:      {c.doc_path}
        """)

    research_result = await researcher.conduct_research()
    report = await researcher.write_report()

    # Get additional information
    research_context = researcher.get_research_context()
    research_costs = researcher.get_costs()
    research_images = researcher.get_research_images()
    research_sources = researcher.get_research_sources()

    return (
        report,
        research_result,
        research_context,
        research_costs,
        research_images,
        research_sources,
    )


def deep_research(
    query,
    report_type="research_report",
    verbose=False,
    skip_refinement=False,
    source="litdb",
):
    """Run deep_research on the QUERY.

    report_type is one of

    research_report: Summary - Short and fast (~2 min)
    detailed_report: Detailed - In depth and longer (~5 min)
    resource_report
    outline_report
    custom_report
    subtopic_report

    when verbose is truthy, provides more output.
    skip_refinement: if True, skip the interactive query refinement step
    source: where the material comes from, a key of REPORT_SOURCES.

    Note: there are two functions, get_report, and this one because of the async
    methods used.

    """
    report, result, context, costs, images, sources = asyncio.run(
        get_report(query, report_type, verbose, skip_refinement, source)
    )

    return report, result, context, costs, images, sources
