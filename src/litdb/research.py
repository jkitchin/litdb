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

import numpy as np
import asyncio
import json
import os

from sentence_transformers import SentenceTransformer
from gpt_researcher import GPTResearcher
from litellm import completion
from langchain.schema import Document

from .utils import get_config
from .db import get_db
from .openalex import get_data, get_text

config = get_config()
db = get_db()


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
    gr_config = config.get("gpt-researcher", {})

    # You won't always need this, but it is harmless to set here.
    os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

    # This may be too clever. You can setup gpt_researcher with environment
    # variables. If those exist, you might override them from litdb.toml. But,
    # if they are not set here, I use defaults. I want this to require as little
    # as possible to just work, but remain flexible to get what you want.

    # see https://docs.gptr.dev/docs/gpt-researcher/llms/llms for examples
    os.environ["FAST_LLM"] = gr_config.get("FAST_LLM", "ollama:llama3.3")
    os.environ["SMART_LLM"] = gr_config.get("SMART_LLM", "ollama:llama3.3")
    os.environ["STRATEGIC_LLM"] = gr_config.get("STRATEGIC_LLM", "ollama:llama3.3")
    os.environ["EMBEDDING"] = gr_config.get("EMBEDDING", "ollama:nomic-embed-text")

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

    # I guess you should be able to override it all here.
    os.environ["RETRIEVER"] = gr_config.get("RETRIEVER", retrievers)


def oa_query(query):
    """Get data from OpenAlex for query."""
    url = "https://api.openalex.org/works"

    params = {
        "filter": f"default.search:{query}",
        "email": config["openalex"].get("email"),
        "api_key": config["openalex"].get("api_key"),
    }

    d = get_data(url, params)

    return d


def extract_json(text: str) -> str:
    """
    Extract the first JSON object or array from `text`.
    Finds the first '{' or '[', then scans forward matching braces/brackets,
    ignoring ones inside string literals. Returns the JSON substring.
    Raises ValueError if no valid JSON is found.
    """
    # 1) Locate first opening brace/bracket
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        raise ValueError("No JSON object or array found in text")

    # 2) Scan forward to find the matching closing brace/bracket
    stack = []
    mapping = {"]": "[", "}": "{"}
    in_string = False
    escape = False

    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if not stack or stack[-1] != mapping[ch]:
                    raise ValueError(f"Mismatched closing {ch!r} at position {i}")
                stack.pop()
                if not stack:
                    # Found the matching closing bracket
                    candidate = text[start : i + 1]
                    # Optional: validate it's real JSON
                    try:
                        json.loads(candidate)
                    except json.JSONDecodeError as e:
                        raise ValueError(f"Extracted text is not valid JSON: {e}")
                    return candidate

    raise ValueError("No matching closing bracket found for JSON start")


def litdb_documents(query):
    """Create the litdb documents.

    Query should be a string.

    Returns a list of langchain Documents.
    """
    config = get_config()
    model = SentenceTransformer(config["embedding"]["model"])
    emb = model.encode([query]).astype(np.float32).tobytes()

    # number of queries to return or generate. This is used in several places. I
    # don't think it makes sense to configure each one independently. We default
    # to 5.
    n_queries = config["gpt-researcher"].get("n_queries", 5)

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

    model = config["llm"].get("model", "ollama/llama3.3")
    response = completion(model=model, messages=msgs)

    try:
        content = response["choices"][0]["message"]["content"].strip()

        js = extract_json(content)

        queries = json.loads(js)["queries"]

    except json.decoder.JSONDecodeError:
        print("Generating full text queries failed on:")
        print(content)
        print(f'The following json was extracted:\n\n"{js}"\n')
        print("Proceeding without full text queries." " Please report this message")
        queries = []

    for i, q in enumerate(queries):
        results = db.execute(
            """select
            sources.source, sources.text, snippet(fulltext, 1, '', '', '', 16),
            sources.extra, bm25(fulltext)
            from fulltext
            inner join sources on fulltext.source = sources.source
            where fulltext.text match ? order by rank limit ?""",
            (f'"{q}"', n_queries),
        ).fetchall()

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


def refine_query(query):
    """Refine the query.

    The goal is to ask some clarifying questions about the query, and then
    refine it to get a better starting point for research.
    """
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
    model = config["llm"].get("model", "ollama/llama3.3")

    response = completion(model=model, messages=msgs, stream=True)
    output = ""
    for chunk in response:
        out = chunk.choices[0].delta.content or ""
        print(out, end="")
        output += out

    reply = input("Enter for no change > ")

    if reply.strip():
        # Now get the user response
        msgs += [
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
            print(out)
            output += out

        query = output

    print(f"Doing research on:\n\n{query}\n\n")

    return query


async def get_report(query: str, report_type: str, verbose: bool):
    """Generate the report.

    QUERY: string to query and generate a report for.

    Adapted from https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package.
    """
    research_env()
    query = refine_query(query)

    docs = litdb_documents(query)

    # for doc in docs:
    #     print(doc)
    #     print('\n-----------\n')

    # if not 'y' in input('continue? ').lower():
    #     import sys
    #     sys.exit()

    researcher = GPTResearcher(
        query=query,
        report_type=report_type,
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


def deep_research(query, report_type="research_report", verbose=False):
    """Run deep_research on the QUERY.

    report_type is one of

    research_report: Summary - Short and fast (~2 min)
    detailed_report: Detailed - In depth and longer (~5 min)
    resource_report
    outline_report
    custom_report
    subtopic_report

    when verbose is truthy, provides more output.

    Note: there are two functions, get_report, and this one because of the async
    methods used.

    """
    report, result, context, costs, images, sources = asyncio.run(
        get_report(query, report_type, verbose)
    )

    return report, result, context, costs, images, sources
