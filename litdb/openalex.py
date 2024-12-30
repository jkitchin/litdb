"""OpenAlex plugin for litdb."""

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ratelimit import limits


# limit openalex calls to 10 per second
@limits(calls=10, period=1)
def get_data(url, params=None):
    """Get json data for URL and PARAMS with rate limiting. If this request
    fails, it prints the status code, but returns an empty dictionary.

    """
    try:
        retry = Retry(
            total=5, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504]
        )

        adapter = HTTPAdapter(max_retries=retry)

        session = requests.Session()
        session.mount("https://", adapter)
        req = session.get(url, params=params, timeout=180)

        if req.status_code == 200:
            return req.json()
        else:
            print("status code: ", req.status_code)
            print("text: ", req.text)
            print("url: ", req.url)
            return {"meta": {"next_cursor": None}, "results": []}

    except Exception as e:
        print(e)


def html_to_text(html_string):
    """Strip html from html_string."""
    if html_string:
        soup = BeautifulSoup(html_string, "html.parser")
        return soup.get_text()
    else:
        return html_string


def get_text(result):
    """Return a rendered text represenation for RESULT.

    This has a pseudo citation with the authors, title, year, and journal, and
    the abstract if available.

    """
    aii = result.get("abstract_inverted_index", None)
    word_index = []

    if aii:
        for k, v in aii.items():
            for index in v:
                word_index.append([k, index])

        word_index = sorted(word_index, key=lambda x: x[1])
        abstract = " ".join([x[0] for x in word_index])
    else:
        abstract = "No abstract"

    abstract = html_to_text(abstract)
    title = result.get("display_name", "") or "No title"
    year = result.get("publication_year", None)
    wid = result["id"]
    doi = result.get("doi", None) or wid

    authors = ", ".join([au["author"]["display_name"] for au in result["authorships"]])
    pl = result.get("primary_location", {}) or {}
    source = pl.get("source", {}) or {}
    host = source.get("display_name", "No source") or "No source"

    return f"{title}, {authors}, {host} ({year}) {doi}\n\n{abstract}"
