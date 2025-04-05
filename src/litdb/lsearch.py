"""LLM-openalex search.

The idea is we use a natural language query to search OpenAlex. this is done by
using an LLM to generate keyword queries that we send to OpenAlex. Then we get
the top n hits for each query and aggregate them.

For each paper, we might generate a score, and then finally return the top k
results.
"""

import json
from litellm import completion
from sentence_transformers import SentenceTransformer
import numpy as np

from .utils import get_config
from .openalex import get_data, get_text

config = get_config()


def oa_query(query, n, sort=None, sample=False):
    """Get data from OpenAlex for query.

    N: int, number of results to retrieve
    SORT: string
    SAMPLE: boolean
    """
    url = "https://api.openalex.org/works"

    params = {
        "per_page": n,
        "filter": f"default.search:{query}",
        "email": config["openalex"].get("email"),
        "api_key": config["openalex"].get("api_key"),
    }
    if sort:
        params.update(sort=sort)

    if sample:
        params.update(sample=n)

    try:
        d = get_data(url, params)
    except:  # noqa: E722
        d = {"results": []}

    return d


def llm_oa_search(query, q=5, n=25, k=5):
    """Run an LLM-based search of OpenAlex.

    QUERY: a natural language query
    Q: int, number of keyword queries to generate
    N: int, number of hits for each query
    K: int, number of results to return

    Runs several queries with different sort orders, and samples. Then all the
    found entries are sorted by vector similarity to the query, and the top k
    results are returned.

    Returns: top K json entries.

    """
    query = " ".join(query)

    msgs = [
        {
            "role": "system",
            "content": f"""You are an expert deep researcher that outputs only
valid JSON. Analyze this query to identify {q} full text queries based on
keywords that could be relevant. Each query should be different to maximize the
chances of finding new papers.

Return a list of {q} queries in json:

{{"queries": [query1, query2, ...]}}

Respond with a JSON object, without backticks or markdown formatting.""",
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
        print("Proceeding without full text queries." " Please report this message")
        queries = []

    results = []
    for i, _q in enumerate(queries):
        print(f'Running "{_q}"')
        for sort in [
            "cited_by_count",
            "cited_by_count:desc",
            "publication_date",
            "publication_date:desc",
        ]:
            result = oa_query(_q, n, sort)
            results += result["results"]
        # and get a sample
        result = oa_query(_q, n, sample=True)
        results += result["results"]

    # remove duplicates
    known_ids = []
    known = []
    for result in results:
        if result["id"] in known_ids:
            pass
        else:
            known_ids += [result["id"]]
            known += [result]

    results = known

    # Now we have all the results. We get documents for each one next
    docs = [get_text(result) for result in results]

    # Now we need some kind of score. We get a vector embedding on each doc
    st = SentenceTransformer(config["embedding"]["model"])
    ref = st.encode([query]).astype(np.float32)
    embs = st.encode(docs).astype(np.float32)

    # use cos distance here
    scores = [
        1 - np.dot(ref, emb) / np.linalg.norm(ref) / np.linalg.norm(emb) for emb in embs
    ]

    topk = sorted(zip(scores, results), key=lambda x: x[0])[0:k]

    return topk
