#!/usr/bin/env python

from more_itertools import batched
import datetime
from IPython import get_ipython
from IPython.display import HTML, display
import pandas as pd
from nameparser import HumanName
import requests
import base64


def get_coa(orcid):
    """Generate Table 4 for the NSF COA.
    ORCID: str the author orcid to retrieve results for.
    """

    url = "https://api.openalex.org/works"

    next_cursor = "*"

    pubs = []

    current_year = datetime.datetime.now().year
    four_years_ago = current_year - 4

    orcid = orcid.replace("https://orcid.org/", "")

    while next_cursor:
        _filter = (
            f"author.orcid:https://orcid.org/{orcid}"
            f",publication_year:>{four_years_ago - 1}"
        )

        r = requests.get(
            url,
            params={
                "filter": _filter,
                "email": "jkitchin@andrew.cmu.edu",
                "cursor": next_cursor,
            },
        )
        data = r.json()
        pubs += data["results"]
        next_cursor = data["meta"].get("next_cursor", None)

    # We get all the authors from all the papers first.
    authors = []

    for pub in pubs:
        year = int(pub.get("publication_year", -1))
        last_active = datetime.datetime.strptime(
            pub.get("publication_date", f"{year}-01-01"), "%Y-%m-%d"
        ).strftime("%m/%m/%Y")

        aus = pub["authorships"]
        for au in aus:
            hn = HumanName(au["author"]["display_name"])
            name = f'{hn.last}, {hn.first} {hn.middle or ""}'

            authors += [[name, year, last_active, au["author"]["id"], pub["id"]]]

    # sort authors alphabetically, then by year descending
    authors = sorted(authors, key=lambda row: (row[0].lower(), -row[1]))

    # Now, get all the affiliations. This assumes the first one is most recent.
    # I could also use the last known institution, but this is sometimes empty
    # too.
    oaids = set([row[3].replace("https://openalex.org/", "") for row in authors])
    affiliations = {}
    for batch in batched(oaids, 50):
        url = f'https://api.openalex.org/authors?filter=id:{"|".join(batch)}'

        params = {"per-page": 50, "email": "jkitchin@andrew.cmu.edu"}

        d = requests.get(url, params=params)

        for au in d.json()["results"]:
            affils = au["affiliations"]
            if len(affils) > 0:
                affiliations[au["id"]] = affils[0]["institution"]["display_name"]
            else:
                affiliations[au["id"]] = ""

    uniq = {}
    uniq_authors = []  # by openalex id
    all_authors = []
    for name, year, last_active, oa_id, pub_id in authors:
        if oa_id not in uniq:
            uniq[oa_id] = 1
            affil = affiliations.get(oa_id, "No affiliation known")
            # now we build the tables
            uniq_authors += [["A:", name, affil, "", last_active]]
            all_authors += [["A:", name, affil, "", last_active, pub_id, oa_id]]

    # unique authors
    df = pd.DataFrame(
        uniq_authors,
        columns=[
            "4",
            "Name:",
            "Organizational Affiliation",
            "Optional (email, Department)",
            "Last Active",
        ],
    )

    today = datetime.date.today().strftime("%Y-%m-%d.xlsx")
    coa_file = f"{orcid}-{today}"

    # Table 4
    xw = pd.ExcelWriter(coa_file, engine="xlsxwriter")
    df.to_excel(xw, index=False, sheet_name="Table 4")

    sheet = xw.sheets["Table 4"]

    for column in df:
        column_length = max(df[column].astype(str).map(len).max(), len(column))
        col_idx = df.columns.get_loc(column)
        sheet.set_column(col_idx, col_idx, column_length + 2)

    # Save all authors for debugging
    authors_df = pd.DataFrame(
        all_authors,
        columns=[
            "4",
            "Name:",
            "Organizational Affiliation",
            "Optional  (email, Department)",
            "Last Active",
            "OpenAlex pub id",
            "OpenAlex author id",
        ],
    )
    authors_df.to_excel(xw, index=False, sheet_name="all authors")

    sheet = xw.sheets["all authors"]
    for column in df:
        column_length = max(df[column].astype(str).map(len).max(), len(column))
        col_idx = df.columns.get_loc(column)
        sheet.set_column(col_idx, col_idx, column_length + 2)

    # Save the Excel file
    xw.close()

    if get_ipython():
        with open(coa_file, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
            uri = f'<pre>{coa_file}</pre><br><a href="data:text/plain;base64,{b64}" download="{coa_file}">Download COA</a>'
            display(HTML(uri))
    else:
        print(f"Created {coa_file}")
