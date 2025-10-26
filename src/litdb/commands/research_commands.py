"""Research-related commands for litdb.

Commands:
- fhresearch: Run FutureHouse research tasks
- research: Run deep research with gpt_researcher
- suggest_reviewers: Suggest reviewers based on similar papers
"""

import json
import os

import click
from IPython import get_ipython
from IPython.display import display, HTML
from more_itertools import batched
from rich import print as richprint
from rich.console import Console
from rich.markdown import Markdown
import tabulate
import webbrowser

from futurehouse_client import FutureHouseClient, JobNames

from ..utils import get_config
from ..openalex import get_data
from ..research import deep_research
from . import search


@click.command()
@click.argument("query", nargs=-1)
@click.option(
    "-t",
    "--task",
    default="crow",
    help="The type of task to run. One of crow, owl, falcon.",
)
def fhresearch(query, task):
    """Run a FutureHouse research TASK on QUERY.

    Tasks:
    crow: General research
    owl: Did anyone do this before?
    falcon: Deep research


    You need to set FUTURE_HOUSE_API_KEY in your env. To get one of those, go to
    https://platform.futurehouse.org/, create an account and get one.

    This is a slow function. It can take 2-10 minutes for the task to be
    completed, with little feedback until the answer returns.

    """

    client = FutureHouseClient(api_key=os.environ["FUTURE_HOUSE_API_KEY"])

    jobs = {"crow": JobNames.CROW, "owl": JobNames.OWL, "falcon": JobNames.FALCON}

    if not isinstance(query, str):
        query = " ".join(query)

    task_response = client.run_tasks_until_done(
        {"name": jobs[task.lower()], "query": query}
    )

    print(task_response[0].formatted_answer)


@click.command()
@click.argument("query", nargs=-1)
@click.option(
    "--report-type", default="research_report", help="The type of report to generate."
)
@click.option("--doc-path", default=None, help="Path to local documents")
@click.option("-o", "--output", default=None, help="output file")
@click.option("-v", "--verbose", is_flag=True, default=False)
def research(query, report_type, doc_path, output, verbose):
    """Run a deep research query.

    QUERY: the topic to do research on

    REPORT_TYPE: one of the supported types in gpt_researcher
    DOC_PATH: a directory path for local files
    OUTPUT: a filename to write output to, defaults to printing to stdout
    VERBOSE: if truthy the output is more verbose.

    Based on gpt_researcher. You need to have some configuration setup in advance.
    API keys for the LLM in environment variables.
    """
    query = " ".join(query)  # if you don't quote the query it is a list of words.

    if doc_path:
        os.environ["DOC_PATH"] = doc_path

    report, result, context, costs, images, sources = deep_research(
        query, report_type, verbose
    )

    s = f"""{report}

# Research costs
${costs}

# Result
{result}

# Context
{context}
"""
    if output:
        base, ext = os.path.splitext(output)
        # I found pypandoc was not good at pdf. lots of bad latex commands that
        # make the pdf build fail.
        # pdfkit relies on wkhtmltopdf which appears discontinued
        # weasyprint and m2pdf has some gobject dependency
        # These are adapted from gpt_researcher / multi_agents

        if ext == ".pdf":
            from md2pdf.core import md2pdf

            md2pdf(output, md_content=s)

        elif ext == ".docx":
            import mistune
            from htmldocx import HtmlToDocx
            from docx import Document

            html = mistune.html(s)
            doc = Document()
            HtmlToDocx().add_html_to_document(html, doc)
            doc.save(output)

        elif ext == ".html":
            import mistune

            html = mistune.html(s)
            with open(output, "w") as f:
                f.write(html)

        elif ext == ".org":
            import pypandoc

            with open(output, "w") as f:
                org = pypandoc.convert_text(s, to="org", format="md")
                f.write(org)

        elif ext == ".md":
            with open(output, "w") as f:
                f.write(s)
        else:
            print(f"I do not know how to make {output}.")

        if os.path.exists(output):
            print(f"Opening {output}")
            webbrowser.open(f"file://{os.path.abspath(output)}")

    else:
        console = Console(color_system="truecolor")

        with console.pager():
            console.print(Markdown(s))


@click.command()
@click.argument("query", nargs=-1)
@click.option("-n", default=5, help="Number of documents to use")
def suggest_reviewers(query, n):
    """Suggest reviewers for QUERY.

    Use up to N similar documents. This is an iterative function, you will be
    prompted to expand the search.
    """
    config = get_config()
    query = " ".join(query)

    # This is a surprise. You can't just call the functions above! This is
    # apparently the way to do this.
    with click.Context(search.vsearch) as ctx:
        results = ctx.invoke(
            search.vsearch, query=query.split(" "), n=n, fmt="", iterative=True
        )

    # Now collect the authors from the matching papers
    authors = []

    for i, row in enumerate(results):
        source, citation, extra, distance = row

        d = json.loads(extra)

        for authorship in d["authorships"]:
            authors += [authorship["author"]["id"]]

    # get the unique ones
    from collections import Counter

    authors = Counter(authors)

    # Get author information
    data = []

    url = "https://api.openalex.org/authors/"
    # You can only filter on 50 ids at a time, so we hard code this limit here
    # and per page.
    for batch in batched(authors, 50):
        url = f"https://api.openalex.org/authors?filter=id:{'|'.join(batch)}"

        params = {"per-page": 50, "mailto": config["openalex"]["email"]}

        r = get_data(url, params)

        for d in r["results"]:
            lki = d.get("last_known_institutions", [])
            if lki == []:
                affils = d.get("affiliations", [])
                if len(affils) >= 1:
                    lki = affils[0]["institution"]["display_name"]
                else:
                    lki = "unknown"

            else:
                if len(lki) >= 1:
                    lki = lki[0].get("display_name")
                else:
                    lki = "unknown"

            row = [
                d["display_name"],
                authors[d["id"]],
                d["summary_stats"]["h_index"],
                d["id"],
                lki,
            ]
            data += [row]

    # Sort and display the results
    data.sort(key=lambda row: row[2], reverse=True)

    if get_ipython():
        display(
            HTML(
                tabulate.tabulate(
                    data,
                    headers=["name", "# papers", "h-index", "oaid", "institution"],
                    tablefmt="html",
                )
            )
        )
        for i, row in enumerate(results):
            source, citation, extra, distance = row
            richprint(f"{i + 1:2d}. {citation} (source)\n\n")

    else:
        s = ["Potential reviewers"]
        s += [
            tabulate.tabulate(
                data,
                headers=["name", "# papers", "h-index", "oaid", "institution"],
                tablefmt="orgtbl",
            )
        ]
        s += ["\n" + "From these papers:"]
        for i, row in enumerate(results):
            source, citation, extra, distance = row
            s += [f"{i + 1:2d}. {citation} (source)\n\n"]

        console = Console(color_system="truecolor")
        with console.pager():
            for _s in s:
                console.print(_s)
