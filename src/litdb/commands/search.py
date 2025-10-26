"""Search commands for litdb.

Commands:
- screenshot: Vector search from OCR'd screenshot
- vsearch: Vector similarity search
- fulltext: Full-text search using FTS5
- lsearch: LLM-enhanced search
- similar: Find similar sources
- image_search: Search with images using CLIP
- hybrid_search: Combined vector and full-text search
"""

import json
import os

import click
from jinja2 import Template
import numpy as np
from rich import print as richprint
from sentence_transformers import SentenceTransformer

from ..utils import get_config
from ..db import get_db, add_work
from ..lsearch import llm_oa_search
from ..images import image_query


# Lazy database initialization - get db when needed
def get_search_db():
    """Get database connection for search commands."""
    return get_db()


@click.command()
def screenshot():
    """Do vector search from text in a screenshot.

    Use OCR to get text from an image on the clipboard (probably from a
    screenshot) and do a vector search on the text.
    """
    from PIL import ImageGrab
    import pytesseract

    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    # Grab the image from the clipboard
    img = ImageGrab.grabclipboard()

    if img:
        text = pytesseract.image_to_string(img)
        print(f'Searching for "{text}"')
        vsearch.callback([text])
    else:
        print("No image found in clipboard.")


@click.command()
@click.argument("query", nargs=-1)
@click.option("-n", default=3)
@click.option("-e", "--emacs", is_flag=True, default=False)
@click.option("-i", "--iterative", is_flag=True, default=False)
@click.option("-m", "--max-steps", default=None)
@click.option(
    "-f",
    "--fmt",
    default=(" {{ i }}. ({{ score|round(3) }}) {{ source }}\n{{ text[:200] }}\n\n"),
)
@click.option("-x", "--cross-encode", is_flag=True, default=False)
def vsearch(query, n, emacs, fmt, cross_encode, iterative, max_steps):
    """Do a vector search on QUERY.

    N is an integer for number of results to return
    EMACS is a flag for changing the output format for emacs

    FORMAT is a jinja template for the output. The variables you have access to
    are i, source, text, extra, similarity.

    CROSS_ENCODE is a boolean that resorts the results with a cross-encoder.

    ITERATIVE is a boolean that expands the search by references, citations and
    related articles from the top matches until you tell it to stop or reach
    MAX_STEPS.

    MAX_STEPS is the maximum number of iterations to take. If you set this, you
    will not be prompted each time, it will just run those steps until nothing
    better is found, or you reach the number.

    """
    db = get_search_db()
    config = get_config()
    query = " ".join(query)
    model = SentenceTransformer(config["embedding"]["model"])
    emb = model.encode([query]).astype(np.float32).tobytes()

    if iterative:
        best = None

        steps = 0

        while True:
            results = db.execute(
                """select
            sources.source, sources.text,
            sources.extra, vector_distance_cos(?, embedding) as d
            from vector_top_k('embedding_idx', ?, ?)
            join sources on sources.rowid = id
            order by d""",
                (emb, emb, n),
            ).fetchall()

            for source, text, extra, d in results:
                richprint(f"{d:1.3f}: {source}")

            steps += 1
            if steps == max_steps:
                break

            current = [x[0] for x in results]  # sources

            # This means no change
            if current == best:
                print("Nothing new was found")
                break

            if not max_steps and input(
                "Search for better matches? ([y]/n)"
            ).lower().startswith("n"):
                break

            # something changed. add references and loop
            best = current
            for source in current:
                add_work(source, True, True, True)

    else:
        c = db.execute(
            """select sources.source, sources.text,
        sources.extra, vector_distance_cos(?, embedding)
        from vector_top_k('embedding_idx', ?, ?)
        join sources on sources.rowid = id""",
            (emb, emb, n),
        )

        results = c.fetchall()

    if cross_encode:
        import torch
        from sentence_transformers.cross_encoder import CrossEncoder

        # I don't know why I have to set the activation function here, but the
        # score is not 0..1 otherwise
        ce = CrossEncoder(
            config["embedding"]["cross-encoder"],
            default_activation_function=torch.nn.Sigmoid(),
        )
        scores = ce.predict([[query, text] for _, text, _, _ in results])
        # resort based on the scores
        results = [results[i] for i in np.argsort(scores)]

    if emacs:
        tmpl = (
            "( {% for source, text, extra, score in results %}"
            '("({{ score|round(3) }}) {{ text }}" . "{{ source }}") '
            "{% endfor %})"
        )
        template = Template(tmpl)
        print(template.render(**locals()))
    else:
        for i, row in enumerate(results, 1):
            source, text, extra, score = row
            template = Template(fmt)
            richprint(template.render(**locals()))

    return results


@click.command()
@click.argument("query", nargs=-1)
@click.option("-n", default=3)
@click.option(
    "-f", "--fmt", default="{{ source }} ({{ score | round(3) }})\n{{ snippet }}"
)
def fulltext(query, n, fmt):
    """Perform a fulltext search on litdb."""
    db = get_search_db()
    query = " ".join(query)

    results = db.execute(
        """select
    sources.source, sources.text, snippet(fulltext, 1, '', '', '', 16), sources.extra, bm25(fulltext)
    from fulltext
    inner join sources on fulltext.source = sources.source
    where fulltext.text match ? order by rank limit ?""",
        (query, n),
    ).fetchall()

    for source, text, snippet, extra, score in results:
        richprint(Template(fmt).render(**locals()))

    return results


@click.command()
@click.argument("query", nargs=-1)
@click.option("-q", default=5, help="The number of queries to generate")
@click.option("-n", default=25, help="The number of results to get for each query")
@click.option("-k", default=5, help="The number of results to return")
def lsearch(query, q, n, k):
    """LLM enhanced search of OpenAlex.

    QUERY: string, an natural language query
    Q: int, number of keyword searches to generate
    N: int, number of results to retrieve for each keyword query
    K: int, number of results to finally return

    Internally, it generates Q keyword queries based on the original QUERY using
    an LLM. For each keyword query several searches are run sorted on citations
    and publication year both ascending and descending, and a random sample is
    searched. Then these are combined and sorted by vector similarity to the
    query. Finally the top k results are printed.

    This does not add anything to the litdb database.

    """
    for s, result in llm_oa_search(query, q, n, k):
        richprint(
            f"{s[0]:1.2f}: {result['title']} ({result['publication_year']}), {result['id']}\n\n"
        )


@click.command()
@click.argument("query", nargs=-1)
@click.option("-c", "--clipboard", is_flag=True, default=False)
@click.option("-n", default=1, help="Number of hits to retrieve")
def image_search(query, clipboard, n):
    """Search for images using CLIP model."""
    image_query(" ".join(query), clipboard, n)


@click.command()
@click.argument("source")
@click.option("-f", "--fmt", default=None)
@click.option("-e", "--emacs", is_flag=True, default=False)
@click.option("-n", default=3)
def similar(source, n, emacs, fmt):
    """Find N sources similar to SOURCE by vector similarity.

    if EMACS is truthy, the output is lisp for Emacs to read.
    FMT is a jinja template with access to source, text, and extra
    """
    db = get_search_db()
    (emb,) = db.execute(
        """select embedding from sources where source = ?""", (source,)
    ).fetchone()

    allrows = db.execute(
        """select sources.source, sources.text, sources.extra
    from vector_top_k('embedding_idx', ?, ?)
    join sources on sources.rowid = id""",
        # we do n + 1 because the first entry is always the source
        (emb, n + 1),
    ).fetchall()

    rows = [(source, text, json.loads(extra)) for source, text, extra in allrows[1:]]

    if emacs:
        template = Template(
            "({% for source, text, extra in rows %}"
            ' ("{{ extra.get("citation") or text }}" . "{{ source }}")'
            " {% endfor %})"
        )
        print(template.render(**locals()))
    else:
        template = Template(fmt or "{{ i }}. {{ source }}\n {{text}}\n\n")
        # print starting at index 1, the first item is always the source.
        for i, row in enumerate(rows, 1):
            source, text, extra = row
            richprint(template.render(**locals()))


@click.command()
@click.argument("vector_query")
@click.argument("text_query")
@click.option("-n", default=5)
@click.option(
    "-f", "--fmt", default="{{ source }} ({{ score | round(3) }})\n{{ text }}\n\n"
)
def hybrid_search(vector_query, text_query, n, fmt):
    """Perform a hybrid vector and full text search.

    VECTOR_QUERY: The query to do vector search on
    TEXT_QUERY: The query for full text search
    N is an integer number of documents to return.
    FMT is a jinja template.
    """
    db = get_search_db()

    # Get vector results and score
    with click.Context(vsearch) as ctx:
        # source, text, extra, score
        vresults = ctx.invoke(vsearch, query=vector_query.split(" "), n=n, fmt="")
        vscores = [(result[0], result[3]) for result in vresults]

    # Get text results and score
    with click.Context(fulltext) as ctx:
        tresults = ctx.invoke(fulltext, query=text_query.split(" "), n=n, fmt="")
        # I think sqlite makes scores negative to sort them the way they want. I
        # reverse this here.
        tscores = [(result[0], -result[-1]) for result in tresults]

    # Normalize scores
    minv, maxv = min([x[1] for x in vscores]), max([x[1] for x in vscores])
    mint, maxt = min([x[1] for x in tscores]), max([x[1] for x in tscores])

    vscores = {oaid: (score - minv) / (maxv - minv) for oaid, score in vscores}
    tscores = {oaid: (score - minv) / (maxv - minv) for oaid, score in tscores}

    combined_scores = {}
    for oaid in set(vscores.keys()).union(tscores.keys()):
        vscore = vscores.get(oaid, 0)
        tscore = tscores.get(oaid, 0)
        cscore = 1 / (1 + vscore) + 1 / (1 + tscore)
        combined_scores[oaid] = cscore

    sorted_results = sorted(combined_scores.items(), key=lambda x: x[1], reverse=True)
    results = []
    for oaid, score in sorted_results:
        c = db.execute(
            "select source, text, extra from sources where source = ?", (oaid,)
        )
        row = c.fetchone()
        results += [[*row, score]]

    for row in results:
        source, text, extra, score = row
        richprint(Template(fmt).render(**locals()))

    return results
