"""CLI for litdb.

The main command is litdb. There are subcommands for the actions.
"""

import os
import datetime
import json
import warnings

import click
import dateparser
from IPython import get_ipython
from IPython.display import display, HTML
from jinja2 import Template
from more_itertools import batched

import requests
from rich import print as richprint
from rich.console import Console
from rich.markdown import Markdown
import tabulate
from tqdm import tqdm
import webbrowser

from futurehouse_client import FutureHouseClient, JobNames

from .utils import get_config
from .db import get_db, add_author, update_filter
from .openalex import get_data
from .audio import get_audio_text, record

from .crawl import spider
from .research import deep_research
from .extract import extract_tables, extract_schema
from .summary import generate_summary

# Import command modules
from .commands import manage, search, export

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")
    from .chat import chat

import logging
from transformers.utils import logging as tulogging

# Disable all Transformers logging
tulogging.set_verbosity_error()

logging.getLogger("pydantic").setLevel(logging.CRITICAL)

warnings.filterwarnings("ignore")
warnings.filterwarnings("ignore", category=UserWarning)

# Lazy database initialization - only load if not in test/import-only mode
# During testing, fixtures will set up the database before commands run
db = None
try:
    db = get_db()
except SystemExit:
    # get_db() calls sys.exit() if no config found
    # This is expected during test imports
    pass


@click.group()
def cli():
    """Group command for litdb."""
    pass


#################
# Add functions #
#################


@cli.command()
@click.argument("query", nargs=-1)
@click.option("--references", is_flag=True)
@click.option("--related", is_flag=True)
@click.option("--citing", is_flag=True)
def crossref(query, references, related, citing):
    """Add entries to litdb from a crossref query."""
    query = " ".join(query)
    resp = requests.get("https://api.crossref.org/works", params={"query": query})

    if resp.status_code == 200:
        data = resp.json()
        for i, item in enumerate(data["message"]["items"]):
            authors = ", ".join(
                [f"{au['given']} {au['family']}" for au in item.get("author", [])]
            )
            source = " ".join(item.get("container-title", ["no source"]))
            published = item.get("published", {}) or {}
            year = published.get("date-parts", [["no year"]])[0][0]
            title = item.get("title", ["no title"])
            richprint(
                f"{i}. {' '.join(title)}, {authors}, {source} ({year}), https://doi.org/{item['DOI']}."
            )

        toadd = input("Enter space separated numbers to add, or return to quit. ")

        if toadd:
            toadd = [int(x) for x in toadd.split(" ")]
            dois = [
                "https://doi.org/" + data["message"]["items"][i]["DOI"] for i in toadd
            ]

            with click.Context(manage.add) as ctx:
                ctx.invoke(
                    manage.add,
                    sources=dois,
                    related=related,
                    references=references,
                    citing=citing,
                )


@cli.command()
@click.argument("text")
@click.option("--references", is_flag=True, help="Add references too.")
@click.option("--related", is_flag=True, help="Add related too.")
@click.option("--citing", is_flag=True, help="Add citing too.")
@click.option("--model", default=None, help="LLM model to use for parsing.")
def fromtext(text, references, related, citing, model):
    """Extract and add references from pasted TEXT.

    TEXT should be a string containing academic references (from PDFs, websites, etc.).
    The command uses an LLM to parse the references and adds them to litdb.
    """
    from .chat import get_completion
    from difflib import SequenceMatcher

    config = get_config()

    # Get model from config if not specified
    if model is None:
        llm_config = config.get("llm", {"model": "ollama/llama2"})
        model = llm_config["model"]

    richprint(f"Parsing references with LLM ({model})...")

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
{text}""",
        }
    ]

    try:
        llm_output = get_completion(model, messages)
        richprint()  # newline after streaming output

        # Try to extract JSON from the output (in case LLM adds markdown)
        llm_output = llm_output.strip()
        if llm_output.startswith("```"):
            # Remove markdown code blocks
            lines = llm_output.split("\n")
            llm_output = "\n".join(
                [
                    line
                    for line in lines
                    if not line.startswith("```") and not line.startswith("json")
                ]
            )

        parsed_refs = json.loads(llm_output)

        if not isinstance(parsed_refs, list):
            richprint("[red]Error: LLM did not return a list of references[/red]")
            return

        if len(parsed_refs) == 0:
            richprint("[yellow]No references found in the text[/yellow]")
            return

        richprint(f"Found {len(parsed_refs)} reference(s)\n")

    except json.JSONDecodeError as e:
        richprint(f"[red]Error parsing LLM output as JSON: {e}[/red]")
        richprint(f"LLM output was:\n{llm_output}")
        return
    except Exception as e:
        richprint(f"[red]Error getting LLM completion: {e}[/red]")
        return

    # Step 2: Process each reference
    dois_to_add = []

    for i, ref in enumerate(parsed_refs, 1):
        title = ref.get("title", "")
        authors = ref.get("authors", [])
        year = ref.get("year")
        journal = ref.get("journal", "")
        doi = ref.get("doi")

        author_str = ", ".join(authors[:3]) if authors else "Unknown authors"
        if len(authors) > 3:
            author_str += " et al."

        richprint(f"{i}. {title}")
        richprint(f"   Authors: {author_str}")
        richprint(f"   Year: {year or 'Unknown'}, Journal: {journal or 'Unknown'}")

        # If DOI exists, use it directly
        if doi and doi.strip():
            doi_clean = doi.strip()
            if not doi_clean.startswith("http"):
                doi_clean = f"https://doi.org/{doi_clean}"
            richprint(f"   [green]✓ DOI found: {doi_clean}[/green]")
            dois_to_add.append(doi_clean)
        else:
            # No DOI, try CrossRef search
            richprint("   [yellow]✗ No DOI, searching CrossRef...[/yellow]")

            # Build query
            query_parts = []
            if title:
                query_parts.append(title)
            if authors:
                query_parts.extend(authors[:2])  # Use first 2 authors
            if year:
                query_parts.append(str(year))

            query = " ".join(query_parts)

            try:
                resp = requests.get(
                    "https://api.crossref.org/works", params={"query": query, "rows": 3}
                )

                if resp.status_code == 200:
                    data = resp.json()
                    items = data.get("message", {}).get("items", [])

                    if not items:
                        richprint("   [red]No matches found in CrossRef[/red]\n")
                        continue

                    # Score the top result
                    best = items[0]
                    best_title = (
                        " ".join(best.get("title", [""])) if best.get("title") else ""
                    )

                    # Calculate similarity score
                    similarity = SequenceMatcher(
                        None, title.lower(), best_title.lower()
                    ).ratio()

                    # Check year match
                    year_match = False
                    if year and best.get("published"):
                        pub_year = best.get("published", {}).get(
                            "date-parts", [[None]]
                        )[0][0]
                        year_match = pub_year == year

                    best_authors = ", ".join(
                        [
                            f"{au.get('given', '')} {au.get('family', '')}".strip()
                            for au in best.get("author", [])[:3]
                        ]
                    )
                    best_year = best.get("published", {}).get("date-parts", [[None]])[
                        0
                    ][0]
                    best_doi = f"https://doi.org/{best['DOI']}"

                    richprint(f"   Best match (similarity: {similarity:.2f}):")
                    richprint(f"   {best_title}")
                    richprint(f"   {best_authors}, {best_year}")
                    richprint(f"   {best_doi}")

                    # Auto-add if high confidence
                    if similarity > 0.85 and (year_match or not year):
                        richprint(
                            "   [green]High confidence match, adding automatically[/green]"
                        )
                        dois_to_add.append(best_doi)
                    else:
                        confirm = input("   Add this? [y/N]: ")
                        if confirm.lower().startswith("y"):
                            dois_to_add.append(best_doi)
                        else:
                            richprint("   [yellow]Skipped[/yellow]")
                else:
                    richprint(f"   [red]CrossRef API error: {resp.status_code}[/red]")

            except Exception as e:
                richprint(f"   [red]Error querying CrossRef: {e}[/red]")

        richprint()  # blank line between references

    # Step 3: Add all collected DOIs
    if dois_to_add:
        richprint(f"\n[bold]Adding {len(dois_to_add)} reference(s) to litdb...[/bold]")
        with click.Context(manage.add) as ctx:
            ctx.invoke(
                manage.add,
                sources=tuple(dois_to_add),
                references=references,
                related=related,
                citing=citing,
            )
        richprint("[green]✓ Done![/green]")
    else:
        richprint("[yellow]No references to add[/yellow]")


###########
# Tagging #
###########
@cli.command()
@click.argument("sources", nargs=-1)
@click.option("-t", "--tag", "tags", multiple=True)
def add_tag(sources, tags):
    """Add tags to sources.

    It is a little annoying to add multiple tags. It looks like this.
    litdb add-tag source -t tag1 -t tag2
    """
    for source in sources:
        # Get source id
        (source_id,) = db.execute(
            "select rowid from sources where source = ?", (source,)
        ).fetchone()

        for tag in tags:
            # get tag id
            tag_id = db.execute(
                "select rowid from tags where tag = ?", (tag,)
            ).fetchone()

            if not tag_id:
                c = db.execute("insert into tags(tag) values (?)", (tag,))
                tag_id = c.lastrowid
                db.commit()
            else:
                # we get a tuple in the first query
                (tag_id,) = tag_id

            # Now add a tag
            db.execute(
                "insert into source_tag(source_id, tag_id) values (?, ?)",
                (source_id, tag_id),
            )
            db.commit()

            print(f"Tagged {source} with {tag}")


@cli.command()
@click.argument("sources", nargs=-1)
@click.option("-t", "--tag", "tags", multiple=True)
def rm_tag(sources, tags):
    """Remove tags from sources.

    It is a little annoying to remove multiple tags. It looks like this.
    litdb rm-tag source -t tag1 -t tag2
    """
    for source in sources:
        # Get source id
        (source_id,) = db.execute(
            "select rowid from sources where source = ?", (source,)
        ).fetchone()

        for tag in tags:
            # get tag id. Assume it exists?
            (tag_id,) = db.execute(
                "select rowid from tags where tag = ?", (tag,)
            ).fetchone()

            c = db.execute(
                """delete from source_tag
            where source_id = ? and tag_id = ?""",
                (source_id, tag_id),
            )

            db.commit()
            print(f"Deleted {c.rowcount} rows ({tag} from {source}")


@cli.command()
@click.argument("tags", nargs=-1)
def delete_tag(tags):
    """Delete each tag.

    This should also delete tags from sources by cascade.
    """
    for tag in tags:
        c = db.execute("delete from tags where tag = ?", (tag,))
        print(f"Deleted {c.rowcount} rows ({tag})")
    db.commit()


@cli.command()
@click.argument("tags", nargs=-1)
@click.option("-f", "--fmt", default='{{ source }}\n{{ extra["citation"] }}')
def show_tag(tags, fmt):
    """Show entries with tags.

    FMT is a jinja template for the output. You have variables of source, text
    and extra.

    I don't have good logic here, we just show all entries. I could probably get
    some basic and logic with sets, but mostly I assume for now you only want
    one tag, so this works. TODO: add something like boolean logic?

    """
    template = Template(fmt)
    for tag in tags:
        for row in db.execute(
            """select
        sources.source, sources.text, sources.extra
        from sources
        inner join source_tag on source_tag.source_id = sources.rowid
        inner join tags on source_tag.tag_id = tags.rowid
        where tags.tag = ?""",
            (tag,),
        ).fetchall():
            source, text, extra = row
            extra = json.loads(extra)
            richprint(template.render(**locals()))


@cli.command()
def list_tags():
    """Print defined tags."""
    print("The following tags are defined.")
    for (tag,) in db.execute("select tag from tags").fetchall():
        print(tag)


##########
# Review #
##########


@cli.command()
@click.option("-s", "--since", default="1 week ago")
@click.option("-f", "--fmt", default=None)
def review(since, fmt):
    """Review new entries added SINCE.

    SINCE should be something dateparser can handle.
    FMT is a jinja template for the output. Defaults to an org-mode template.
    """

    since = dateparser.parse(since).strftime("%Y-%m-%d")
    c = db.execute(
        """select source, text, extra from sources
    where date(date_added) > ?""",
        (since,),
    ).fetchall()

    template = Template(
        fmt
        or """* {{ extra['display_name'] | replace("\n", " ") }}
:PROPERTIES:
:SOURCE: {{ source }}
:OPENALEX: {{ extra.get('id') }}
:YEAR: {{ extra.get('publication_year') }}
:REFERENCE_COUNT: {{ extra.get('referenced_works_count', 0) }}
:CITED_BY_COUNT: {{ extra.get('cited_by_count', 0) }}
:END:

{{ text }} litdb:{{ source }}
        """
    )

    for source, text, extra in c:
        extra = json.loads(extra) or {}
        print(template.render(**locals()))


@cli.command()
@click.option("-s", "--since", default="1 week")
@click.option("-o", "--output", default=None, help="Output file path (optional)")
@click.option("--model", default=None, help="LLM model to use (optional)")
def summary(since, output, model):
    """Generate a newsletter-style summary of articles added SINCE.

    SINCE: Time period to look back (e.g., "1 week", "2 weeks", "1 month").
    Uses dateparser, so flexible date formats are supported.

    OUTPUT: Optional file path to save the summary. If not provided, outputs to stdout.

    MODEL: LLM model to use for analysis (uses config default if not specified).

    This command:
    1. Fetches articles added since the specified date
    2. Extracts topics from each article using an LLM
    3. Aggregates topics into 5-10 main themes with subtopics
    4. Classifies each article into topics/subtopics
    5. Generates narrative summaries for each subtopic
    6. Outputs an org-mode formatted newsletter

    Example:
        litdb summary -s "2 weeks" -o newsletter.org
    """
    generate_summary(since=since, output_file=output, model=model)


#############
# Searching #
#############


@cli.command()
@click.option("-p", "--playback", is_flag=True, help="Play audio back")
def audio(playback=False):
    """Record audio, convert it to text, and do a vector search on the text.

    The idea is nice, but the quality of transcription for scientific words is
    not that great. A better transcription library might make this more useful.
    """

    while True:
        afile = record()
        text = get_audio_text(afile)
        print("\n" + text + "\n")

        if playback:
            import playsound

            playsound.playsound(afile, block=True)

        response = input("Is that what you want to search? ([y]/n/q): ")
        if response.lower().startswith("q"):
            return
        elif response.lower().startswith("n"):
            # record a new audio
            continue
        else:
            # move on to searching
            break

    search.vsearch.callback([text])


@click.command(help=chat.__doc__)
@click.option("--model", default=None, help="The LiteLLM model to use.")
@click.option("--debug", is_flag=True, default=False)
def chat_command(model, debug):
    chat(model, debug)


cli.add_command(chat_command, name="chat")


@cli.command(help=spider.__doc__)
@click.argument("root")
def crawl(root):
    """Crawl a website at ROOT url."""
    spider(root)


@cli.command()
@click.argument(
    "pdf", type=click.Path(exists=True, dir_okay=False, readable=True), required=True
)
@click.option(
    "-t",
    "--tables",
    type=int,
    multiple=True,
    help="Table numbers to extract (1-based index).",
)
@click.option("-f", "--fmt", default="csv")
def extract(pdf, tables, fmt):
    """Extract tables from a pdf.

    PDF: string, path to file
    TABLES: list of int, the table numbers to extract, starting at 1
    FMT: string, output format.
    """

    for df in extract_tables(pdf, tables):
        match fmt:
            case "csv":
                print(df.to_csv(index=False))
            case "json":
                print(df.to_json(index=False))
            case "md":
                print(df.to_markdown(index=False))
            case _:
                print(df)
        print()


@cli.command()
@click.argument("source", type=str, required=True)
@click.argument("schema", type=str, required=True)
def schema(source, schema):
    """Extract structured schema from a SOURCE.

    SOURCE: string, url or path to file
    SCHEMA: string, the scheme to extract. Comma separated name type.
    """
    print(extract_schema(source, schema))


@cli.command()
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


@cli.command()
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

        import webbrowser

        if os.path.exists(output):
            print(f"Opening {output}")
            webbrowser.open(f"file://{os.path.abspath(output)}")

    else:
        console = Console(color_system="truecolor")

        with console.pager():
            console.print(Markdown(s))


@cli.command()
@click.argument("query", nargs=-1)
@click.option("-g", "--google", is_flag=True)
@click.option("-gs", "--google-scholar", is_flag=True)
@click.option("-pm", "--pubmed", is_flag=True)
@click.option("-ar", "--arxiv", is_flag=True)
@click.option("-cr", "--chemrxiv", is_flag=True)
@click.option("-br", "--biorxiv", is_flag=True)
@click.option("-a", "--all", is_flag=True)
def web(query, google, google_scholar, pubmed, arxiv, chemrxiv, biorxiv, all):
    """Open a web search for QUERY.

    We always do an OpenAlex search.

    If these are true, we also search here
    GOOGLE
    GOOGLE_SCHOLAR
    PUBMED
    ARXIV
    CHEMRXIV
    BIORXIV
    """
    query = " ".join(query)

    if all:
        google, google_scholar = (
            True,
            True,
        )
        pubmed, arxiv, chemrxiv, biorxiv = True, True, True, True

    # This is to avoid some huggingface/tokenizer warning. I don't know why we
    # need to do it, but this code forks the process, and triggers that warning.
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    oa = f"https://openalex.org/works?filter=default.search:{query}"
    webbrowser.open(oa)

    if google:
        url = f"https://www.google.com/search?q={query}"
        webbrowser.open(url)

    if google_scholar:
        url = f"https://scholar.google.com/scholar?q={query}"
        webbrowser.open(url)

    if pubmed:
        url = f"https://pubmed-ncbi-nlm-nih-gov.cmu.idm.oclc.org/?term={query}"
        webbrowser.open(url)

    if arxiv:
        url = f"https://arxiv.org/search/?query={query}"
        webbrowser.open(url)

    if chemrxiv:
        url = f"https://chemrxiv.org/engage/chemrxiv/search-dashboard?text={query}"
        webbrowser.open(url)

    if biorxiv:
        url = f"https://www.biorxiv.org/search/{query}"
        webbrowser.open(url)


###########
# Filters #
###########


@cli.command()
@click.argument("_filter")
@click.option("-d", "--description")
def add_filter(_filter, description=None):
    """Add an OpenAlex FILTER.

    This does not run the filter right away. You need
    to manually update the filters later.
    """
    db.execute(
        "insert into queries(filter, description) values (?, ?)", (_filter, description)
    )
    db.commit()


@cli.command()
@click.argument("_filter")
def rm_filter(_filter):
    """Remove an OpenAlex FILTER."""
    db.execute("delete from queries where filter = ?", (_filter,))
    db.commit()


update_filter_fmt = """** {{ extra['display_name'] | replace("\n", "") | replace("\r", "") }}
:PROPERTIES:
:SOURCE: {{ source }}
:REFERENCE_COUNT: {{ extra.get('referenced_works_count', 0) }}
:CITED_BY_COUNT: {{ extra.get('cited_by_count', 0) }}
:END:

litdb:{{ source }}

{{ text }}

"""


@cli.command()
@click.option("-f", "--fmt", default=update_filter_fmt)
@click.option("-s", "--silent", is_flag=True, default=False)
def update_filters(fmt, silent):
    """Update litdb using a filter with works from a created date."""

    os.environ["TRANSFORMERS_OFFLINE"] = "1"  # Prevent checking HF on each filter
    filters = db.execute("""select filter, description, last_updated from queries""")
    for f, description, last_updated in tqdm(filters.fetchall(), disable=silent):
        try:
            results = update_filter(f, last_updated, silent)
            if results:
                richprint(f"* {description or f}")
            for result in results:
                source, text, extra = result
                richprint(Template(fmt).render(**locals()))
        except:  # noqa: E722
            continue


list_filter_fmt = (
    '{{ "{:3d}".format(rowid) }}.'
    ' {{ "{:30s}".format(description'
    ' or "None") }} {{ f }}'
    " ({{ last_updated }})"
)


@cli.command()
@click.option("-f", "--fmt", default=list_filter_fmt)
def list_filters(fmt):
    """List the filters.

    FMT is a jinja template with access to the variables rowid, f, description
    and last_updated. f is the filter string.

    You can dump the filters to stdout like this.

    > litdb list-filters -f 'litdb add-filter {{ f }}'

    You could use that to send a list of your filters to someone, or to recreate
    a db somewhere else.
    """
    filters = db.execute(
        """select rowid, filter, description, last_updated
    from queries"""
    )
    for rowid, f, description, last_updated in filters.fetchall():
        richprint(Template(fmt).render(**locals()))


######################
# OpenAlex searching #
######################


@cli.command()
@click.argument("query", nargs=-1)
@click.option("-f", "--filter", "_filter", is_flag=True, default=False)
@click.option("-e", "--endpoint", default="works")
@click.option("--sample", default=-1)
@click.option("--per-page", default=5)
def openalex(query, _filter, endpoint, sample, per_page):
    """Run an openalex query on FILTER.

    ENDPOINT should be one of works, authors, or another entity.
    SAMPLE: int, return this many random samples
    PER_PAGE: limits the number of results retrieved

    This does not add anything to your database. It is to help you find starting
    points.

    To search text:
    litdb openalex "circular polymer"

    To find a journal id with a specific filter
    litdb openalex -e sources -f "display_name.search:Digital Discovery"

    """
    config = get_config()
    url = f"https://api.openalex.org/{endpoint}"

    if isinstance(query, tuple):
        query = " ".join(query)
    if not _filter:
        query = f"default.search:{query}"

    params = {
        "mailto": config["openalex"]["email"],
        "filter": query,
        "per_page": per_page,
    }

    if api_key := config["openalex"].get("api_key"):
        params.update(api_key=api_key)

    if sample > 0:
        params.update(sample=sample, per_page=sample)

    resp = requests.get(url, params)
    if resp.status_code != 200:
        print(resp.url)
        print(resp.text)
        return

    data = resp.json()
    for result in data["results"]:
        s = f"{result['title']}, ({result['publication_year']}) {result['id']}\n"
        # Note sometimes there is an exception from bad markup in strings
        richprint(s)


########################################
# Convenience functions to add filters #
########################################


@cli.command()
@click.argument("name", nargs=-1)
def author_search(name):
    """Search OpenAlex for name.

    Uses the autocomplete endpoint to find an author's orcid.
    """
    auname = " ".join(name)

    url = "https://api.openalex.org/autocomplete/authors"

    from .openalex import get_data

    data = get_data(url, params={"q": auname})

    for result in data["results"]:
        richprint(
            f"- {result['display_name']}\n  {result['hint']} "
            f"{result['external_id']}\n\n"
        )


@cli.command()
@click.argument("orcids", nargs=-1)
@click.option("-r", "--remove", is_flag=True, help="remove")
def follow(orcids, remove=False):
    """Add a filter to follow orcid."""
    for orcid in orcids:
        if not orcid.startswith("http"):
            orcid = f"https://orcid.org/{orcid}"

        # Seems like we should get their articles first.
        add_author(orcid)

        f = f"author.orcid:{orcid}"

        if remove:
            c = db.execute("""delete from queries where  filter = ?""", (f,))
            db.commit()
            richprint(f"{c.rowcount} rows removed")
            return

        url = f"https://api.openalex.org/authors/{orcid}"
        data = get_data(url)
        name = data["display_name"]

        today = datetime.date.today().strftime("%Y-%m-%d")
        db.execute(
            """insert or ignore into
        queries(filter, description, last_updated)
        values (?, ?, ?)""",
            (f, name, today),
        )

        richprint(f"Following {name}: {orcid}")
        db.commit()


@cli.command()
@click.argument("query", nargs=-1)
@click.option("-r", "--remove", is_flag=True, help="remove")
def watch(query, remove=False):
    """Create a watch on query.

    QUERY: string, a filter for openalex.
    REMOVE: a flag to remove the query.
    """
    # First, we should make sure the filter is valid
    query = " ".join(query)

    if remove:
        c = db.execute("""delete from queries where filter = ?""", (query,))
        db.commit()
        richprint(f"{c.rowcount} rows removed")
        return

    url = "https://api.openalex.org/works"

    data = get_data(url, params={"filter": query})
    if len(data["results"]) == 0:
        richprint(f"Sorry, {query} does not seem valid.")

    if remove:
        c = db.execute("""delete from queries where filter = ?""", (query,))
        richprint(f"Deleted {c.rowcount} rows")
        db.commit()
    else:
        c = db.execute(
            """insert or ignore into queries(filter, description)
        values (?, ?)""",
            (query,),
        )
        richprint(f"Added {c.rowcount} rows")
        db.commit()
        richprint(f"Watching {query}")


@cli.command()
@click.argument("doi")
@click.option("-r", "--remove", is_flag=True, help="remove")
def citing(doi, remove=False):
    """Create a watch for articles that cite doi.

    REMOVE is a flag to remove the doi.
    """
    url = "https://api.openalex.org/works"

    # We need an OpenAlex id
    f = f"doi:{doi}"

    data = get_data(url, params={"filter": f})
    if len(data["results"]) == 0:
        richprint(f"Sorry, {doi} does not seem valid.")

    wid = data["results"][0]["id"]

    if remove:
        c = db.execute("""delete from queries where filter = ?""", (f"cites:{wid}",))
        db.commit()
        richprint(f"Deleted {c.rowcount} rows")
    else:
        c = db.execute(
            """insert or ignore into queries(filter, description)
        values (?, ?)""",
            (f"cites:{wid}", f"Citing papers for {doi}"),
        )

        db.commit()
        richprint(f"Added {c.rowcount} rows")


@cli.command()
@click.argument("doi")
@click.option("-r", "--remove", is_flag=True, help="remove")
def related(doi, remove=False):
    """Create a watch for articles that are related to doi.

    REMOVE is a flag to remove the doi from queries.
    """
    url = "https://api.openalex.org/works"

    # We need an OpenAlex id
    f = f"doi:{doi}"

    data = get_data(url, params={"filter": f})
    if len(data["results"]) == 0:
        richprint(f"Sorry, {doi} does not seem valid.")

    wid = data["results"][0]["id"]

    if remove:
        c = db.execute(
            """delete from queries where filter = ?""", (f"related_to:{wid}",)
        )
        db.commit()
        richprint(f"Deleted {c.rowcount} rows")
    else:
        c = db.execute(
            """insert or ignore into queries(filter, description)
        values (?, ?)""",
            (f"related_to:{wid}", f"Related papers for {doi}"),
        )

        db.commit()
        richprint(f"Added {c.rowcount} rows")


#############
# Utilities #
#############


@cli.command()
@click.argument("doi")
def unpaywall(doi):
    """Use unpaywall to find PDFs for doi."""
    config = get_config()
    url = f"https://api.unpaywall.org/v2/{doi}"
    params = {"mailto": config["openalex"]["email"]}

    resp = requests.get(url, params)
    if resp.status_code == 200:
        data = resp.json()
        richprint(f"{data['title']}, {data.get('journal_name') or ''}")
        richprint(f"Is open access: {data.get('is_oa', False)}")

        for loc in data.get("oa_locations", []):
            richprint(loc.get("url_for_pdf") or loc.get("url_for_landing_page"))
    else:
        richprint(f"{doi} not found in unpaywall")


######################
# Academic functions #
######################


@cli.command()
@click.argument("orcid")
def coa(orcid):
    """Generate Table 4 of Collaborators and Other Affiliations for NSF.

    ORCID is an orcid URL for the user to generate the table for.
    The file is saved in {orcid}-{today}.xlsx.
    """
    from .coa import get_coa

    get_coa(orcid)


@cli.command()
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


@cli.command()
def app():
    """Launch the Streamlit app in the default web browser."""
    dirname = os.path.dirname(__file__)
    app = os.path.join(dirname, "app.py")
    os.system(f"streamlit run {app}")


@cli.command()
def version():
    """Print the version of litdb."""
    import pkg_resources

    version = pkg_resources.get_distribution("litdb").version
    print(f"Litdb: version {version}")


# Register commands from manage module
cli.add_command(manage.init)
cli.add_command(manage.add)
cli.add_command(manage.remove)
cli.add_command(manage.index)
cli.add_command(manage.reindex)
cli.add_command(manage.update_embeddings)

# Register commands from search module
cli.add_command(search.screenshot)
cli.add_command(search.vsearch)
cli.add_command(search.fulltext)
cli.add_command(search.lsearch)
cli.add_command(search.image_search)
cli.add_command(search.similar)
cli.add_command(search.hybrid_search)

# Register commands from export module
cli.add_command(export.bibtex)
cli.add_command(export.citation)
cli.add_command(export.show)
cli.add_command(export.visit)
cli.add_command(export.about)
cli.add_command(export.sql)


if __name__ == "__main__":
    cli()
