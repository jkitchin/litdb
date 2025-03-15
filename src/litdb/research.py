"""Deep research for litdb.

TODO: integrate OpenAlex as a retriever
TODO: integrate litdb as a retriever, vector search and full text
"""

from gpt_researcher import GPTResearcher
import asyncio
import os
from .utils import get_config

config = get_config()

gpt_researcher = config.get("gpt-researcher", {})

# You won't always need this, but it is harmless to set here.
os.environ["OLLAMA_BASE_URL"] = "http://localhost:11434"

# This may be too clever. You can setup gpt_researcher with environment
# variables. If those exist, you might override them from litdb.toml. But, if
# they are not set here, I use defaults. I want this to require as little as
# possible to just work, but remain flexible to get what you want.

# see https://docs.gptr.dev/docs/gpt-researcher/llms/llms for examples
os.environ["FAST_LLM"] = gpt_researcher.get("FAST_LLM", "ollama:llama3.3")
os.environ["SMART_LLM"] = gpt_researcher.get("SMART_LLM", "ollama:llama3.3")
os.environ["STRATEGIC_LLM"] = gpt_researcher.get("STRATEGIC_LLM", "ollama:llama3.3")
os.environ["EMBEDDING"] = gpt_researcher.get("EMBEDDING", "ollama:nomic-embed-text")

# Where to get data
retrievers = "arxiv"

# API keys
if "NCBI_API_KEY" in os.environ:
    print("Adding pubmed search")
    retrievers += ",pubmed_central"


if "GOOGLE_CX_KEY" in os.environ:
    print("Adding google search")
    retrievers += ",google"


os.environ["RETRIEVER"] = gpt_researcher.get("RETRIEVER", retrievers)


async def get_report(query: str, report_type: str, verbose: bool):
    """Generate the report.

    QUERY: string to query and generate a report for.

    Adapted from https://docs.gptr.dev/docs/gpt-researcher/gptr/pip-package.
    """
    researcher = GPTResearcher(query, report_type, verbose)

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
