"""Library to ingest bibtex files."""


import litdb.db
import bibtexparser
from .openalex import add_work
from tqdm import tqdm


def add_bibtex(bibfile):
    """Add entries with a DOI from bibfile.

    TODO: save entry as extra?
    TODO: add entries with no DOI as text?
    """
    
    with open(bibfile, 'r', encoding='utf-8', errors='replace') as bibfile:
        bib_database = bibtexparser.load(bibfile)
    
        for entry in tqdm(bib_database.entries):
            if 'doi' in entry:
                doi = entry['doi']
                if doi.startswith('http'):
                    add_work(doi)
                elif doi.startswith('10'):
                    add_work(f'https://doi.org/{doi}')
                else:
                    print(f'I do not know what to do with "{doi}"')
                
