"""Deep research for litdb.

This is mostly a wrapper around gpt_researcher with the following additions:

1. The initial query is refined before proceeding.
2. A vector search is used to provide related content from litdb
3. A full-text search is used to provide related content from litdb
4. OpenAlex queries are used to provide related content

The whole thing is wrapped into the litdb cli for convenience.
"""

import numpy as np
import asyncio
import json
import os
import tempfile

from sentence_transformers import SentenceTransformer
from gpt_researcher import GPTResearcher
from litellm import completion

from .utils import get_config
from .db import get_db
from .openalex import get_data, get_text

config = get_config()
db = get_db()


def research_env():
    """Setup the environment variables.

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
    # variables. If those exist, you might override them from litdb.toml. But, if
    # they are not set here, I use defaults. I want this to require as little as
    # possible to just work, but remain flexible to get what you want.

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


def litdb_documents(query):
    """Create the litdb documents.

    Returns a document path."""

    config = get_config()
    query = " ".join(query)
    model = SentenceTransformer(config["embedding"]["model"])
    emb = model.encode([query]).astype(np.float32).tobytes()

    results = db.execute(
        """select
            sources.source, sources.text,
            sources.extra, vector_distance_cos(?, embedding) as d
            from vector_top_k('embedding_idx', ?, ?)
            join sources on sources.rowid = id
            order by d""",
        (emb, emb, 5),
    ).fetchall()

    tdir = tempfile.mkdtemp()
    for i, (source, text, extra, d) in enumerate(results):
        fname = os.path.join(tdir, f"v-{i}.md")
        with open(fname, "w") as f:
            f.write(f"{source}\n\n{text}\n\n{extra}")

    # Full text search - Ideally I would use litellm for enforcing json, but not
    # all models support that, notably gemini doesn't seem to support it, and I
    # use that one a lot.
    msgs = [
        {
            "role": "system",
            "content": """You are an expert deep researcher that outputs only
valid JSON. Analyze this query to identify full text queries that could be
relevant. The queries will be used with sqlite fts5.

             Return a list of 5 queries in json:

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
        # this is janky, but sometimes the model uses backticks anyway
        # This seems easier than some kind of regexp to match
        if content.startswith("```json"):
            content = content.replace("```json", "")
            content = content.replace("```", "")

        queries = json.loads(content)["queries"]
    except json.decoder.JSONDecodeError:
        print("Generating full text queries failed on")
        print(content)
        print("Proceeding without full text queries. Please report this message")
        queries = []

    for i, q in enumerate(queries):
        results = db.execute(
            """select
    sources.source, sources.text, snippet(fulltext, 1, '', '', '', 16), sources.extra, bm25(fulltext)
    from fulltext
    inner join sources on fulltext.source = sources.source
    where fulltext.text match ? order by rank limit ?""",
            (f'"{q}"', 5),
        ).fetchall()

        for j, (source, text, snippet, extra, score) in enumerate(results):
            fname = os.path.join(tdir, f"ft-{i}-{j}.md")
            with open(fname, "w") as f:
                f.write(f"{source}\n\n{text}\n\n{extra}")

        # OpenAlex queries
        oa = oa_query(q)
        for j, result in enumerate(oa["results"][0:5]):
            fname = os.path.join(tdir, f"oa-{i}-{j}.md")
            with open(fname, "w") as f:
                f.write(get_text(result))

    return tdir


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
            "content": f"<reply>{input('(Enter for no change > ') or 'Make no changes'}</reply>",
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

    return output


async def get_report(query: str, report_type: str, verbose: bool):
    """Generate the report.

    QUERY: string to query and generate a report for.

    Adapted from https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package.
    """
    research_env()

    query = " ".join(query)

    query = refine_query(query)

    researcher = GPTResearcher(query=query, report_type=report_type, verbose=verbose)

    # This is where we get information from your litdb in the process. It is a
    # little janky, and relies on a local file mechanism. I haven't figured out
    # if there is a way to do this with the documents argument instead, and I
    # don't know if there is a mechanism to define your own retriever yet for
    # gpt_researcher.
    researcher.cfg.doc_path = litdb_documents(query)

    if verbose:
        c = researcher.cfg
        print(f"""CONFIG:
        retrievers:    {c.retrievers}

        fast_llm:      {c.fast_llm}
        smart_llm:     {c.smart_llm}
        strategic_llm: {c.strategic_llm}
        embedding:     {c.embedding}

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
