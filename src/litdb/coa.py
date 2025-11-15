#!/usr/bin/env python

from more_itertools import batched
import datetime
from IPython import get_ipython
from IPython.display import HTML, display
import pandas as pd
from nameparser import HumanName
import requests
import base64
from io import BytesIO


def get_coa(orcid, email=None):
    """Generate Table 4 for the NSF COA.
    ORCID: str the author orcid to retrieve results for.
    email: str optional email for OpenAlex API (for polite pool)
    """
    print(f"Starting COA generation for ORCID: {orcid}")

    url = "https://api.openalex.org/works"

    next_cursor = "*"

    pubs = []

    current_year = datetime.datetime.now().year
    four_years_ago = current_year - 4
    print(f"Fetching publications from {four_years_ago} to {current_year}...")

    orcid = orcid.replace("https://orcid.org/", "")

    while next_cursor:
        _filter = (
            f"author.orcid:https://orcid.org/{orcid}"
            f",publication_year:>{four_years_ago - 1}"
        )

        params = {
            "filter": _filter,
            "cursor": next_cursor,
        }

        # Only include mailto if email is provided
        if email:
            params["mailto"] = email

        r = requests.get(url, params=params)
        r.raise_for_status()  # Raise exception for bad status codes
        data = r.json()

        # Check if the response has the expected structure
        if "results" not in data:
            raise ValueError(
                f"Unexpected API response. Status: {r.status_code}, Response: {data}"
            )

        pubs += data["results"]
        next_cursor = data["meta"].get("next_cursor", None)

    print(f"Found {len(pubs)} publications")

    # We get all the authors from all the papers first.
    print("Extracting authors from publications...")
    authors = []

    for pub in pubs:
        year = int(pub.get("publication_year", -1))
        last_active = datetime.datetime.strptime(
            pub.get("publication_date", f"{year}-01-01"), "%Y-%m-%d"
        ).strftime("%m/%m/%Y")

        aus = pub["authorships"]
        for au in aus:
            hn = HumanName(au["author"]["display_name"])
            name = f"{hn.last}, {hn.first} {hn.middle or ''}"

            authors += [[name, year, last_active, au["author"]["id"], pub["id"]]]

    # sort authors alphabetically, then by year descending
    authors = sorted(authors, key=lambda row: (row[0].lower(), -row[1]))
    print(f"Found {len(authors)} total author entries (including duplicates)")

    # Now, get all the affiliations using a two-strategy approach:
    # 1. Use last_known_institutions (from most recent publication)
    # 2. Fall back to affiliation with most recent year in affiliations array
    oaids = set([row[3].replace("https://openalex.org/", "") for row in authors])
    print(f"Found {len(oaids)} unique authors")
    print("Fetching affiliation information from OpenAlex...")
    affiliations = {}
    batch_num = 0
    for batch in batched(oaids, 50):
        batch_num += 1
        print(f"  Fetching batch {batch_num} of authors...")
        url = f"https://api.openalex.org/authors?filter=id:{'|'.join(batch)}"

        params = {"per-page": 50}

        # Only include mailto if email is provided
        if email:
            params["mailto"] = email

        d = requests.get(url, params=params)

        for au in d.json()["results"]:
            affiliation_name = ""

            # Strategy 1: Use last_known_institutions (most recent publication)
            last_known = au.get("last_known_institutions", [])
            if last_known and len(last_known) > 0:
                affiliation_name = last_known[0].get("display_name", "")

            # Strategy 2: If no last_known_institutions, use affiliation with most recent year
            if not affiliation_name:
                affils = au.get("affiliations", [])
                if len(affils) > 0:
                    # Find affiliation with most recent year
                    best_affil = max(affils, key=lambda a: max(a.get("years", [0])))
                    affiliation_name = best_affil["institution"]["display_name"]

            affiliations[au["id"]] = affiliation_name

    print("Building unique author list...")
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

    print(f"Creating Excel file with {len(uniq_authors)} unique authors...")

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
    filename = f"{orcid}-{today}"

    # Determine output path
    if get_ipython():
        # Jupyter: use in-memory buffer
        buffer = BytesIO()
        xw = pd.ExcelWriter(buffer, engine="xlsxwriter")
    else:
        # MCP/CLI: save to Downloads folder
        from pathlib import Path

        downloads_path = Path.home() / "Downloads" / filename
        xw = pd.ExcelWriter(str(downloads_path), engine="xlsxwriter")

    # Table 4
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
        # Jupyter: display download link
        excel_bytes = buffer.getvalue()
        b64 = base64.b64encode(excel_bytes).decode("utf-8")
        uri = f'<pre>{filename}</pre><br><a href="data:application/vnd.openxmlformats-officedocument.spreadsheetml.sheet;base64,{b64}" download="{filename}">Download COA</a>'
        display(HTML(uri))
        print("✓ COA generation complete!")
        return None
    else:
        # Return path for MCP server / CLI
        print(f"✓ COA saved to: {downloads_path}")
        return str(downloads_path)
