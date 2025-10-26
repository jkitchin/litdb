"""Data processing and extraction commands for litdb.

Commands:
- crossref: Add entries from CrossRef search
- fromtext: Extract and add references from pasted text using LLM
- extract: Extract tables from PDF files
- schema: Extract structured data using schema
- crawl: Crawl a website
"""

import json
from difflib import SequenceMatcher

import click
import requests
from rich import print as richprint

from ..extract import extract_tables, extract_schema
from . import manage


@click.command()
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


@click.command()
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
    from ..chat import get_completion
    from ..utils import get_config

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


@click.command()
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


@click.command()
@click.argument("source", type=str, required=True)
@click.argument("schema", type=str, required=True)
def schema(source, schema):
    """Extract structured schema from a SOURCE.

    SOURCE: string, url or path to file
    SCHEMA: string, the scheme to extract. Comma separated name type.
    """
    print(extract_schema(source, schema))


@click.command()
@click.argument("root")
def crawl(root):
    """Crawl through ROOT website and add documents to litdb."""
    # Import spider here (scrapy is an optional dependency in crawl extra)
    from ..crawl import spider

    spider(root)
