"""CLI for litdb

The main command is litdb. There are subcommands
"""

import click
from rich import print
import os
from sentence_transformers import SentenceTransformer
import bs4
import requests
import datetime

from tqdm import tqdm

from . import root, CONFIG, config
from .openalex import get_data, add_work, add_author, get_text
from .bibtex import add_bibtex
from .db import db, add_source

@click.group()
def cli():
    """Group command for litdb."""
    pass


@cli.command()
@click.argument('sources', nargs=-1)
@click.option('--references', is_flag=True, help='Add references too.')
@click.option('--related', is_flag=True, help='Add related too.')
@click.option('--citing', is_flag=True, help='Add citing too.')
def add(sources, references=False, citing=False, related=False):
    """Add SOURCES to the db.

    SOURCES can be one or more of a doi or orcid, a pdf path, a url, bibtex
    file, or other kind of file assumed to be text.

    """
    for source in tqdm(sources):

        # a work
        if 'doi.org' in source:
            add_work(source, references, citing, related)

        # works from an author
        elif 'orcid' in source:
            add_author(source)

        # pdf
        elif source.endswith('.pdf'):
            import litdb.pdf
            litdb.pdf.add_pdf(source)

        # docx
        elif source.endswith('.docx'):
            from docx import Document
            doc = Document(source)
            add_source(source, '\n'.join([para.text for para in doc.paragraphs]))

        # pptx
        elif source.endswith('.pptx'):
            from pptx import Presentation
            prs = Presentation(source)
            text = []
            for slide in prs.slides:
                for shape in slide.shapes:
                    if hasattr(shape, "text"):
                        text.append(shape.text)
            add_source(source, '\n'.join(text))

        # a url
        elif source.startswith('http'):
            soup = bs4.BeautifulSoup(requests.get(source).text)
            add_source(source, soup.get_text())

        # a bibtex file
        elif source.endswith('.bib'):
            add_bibtex(source)

        # assume it is text
        else:            
            with open(source) as f:
                text = f.read()
            add_source(source, text)



@cli.command()
@click.argument('query')
def fulltext(query):
    """Perform a fulltext search on litdb.
    """
    for source, text in db.execute('''select source, text
    from fulltext
    where text match ? order by rank''',
    [query]):
        print(f"[link]{source}[/link]")
        print(text + '\n')

        
@cli.command()
@click.argument('query')
def vsearch(query):
    model = SentenceTransformer(config['embedding']['model'])
    emb = model.encode([query])
    for (source, chunk, d) in db.execute('''select sources.source, chunks.chunk, distance
    from embeddings
    left join chunks on chunks.rowid = embeddings.rowid
    left join sources on chunks.sourceid = sources.rowid
    where embedding match :emb and k=:k''', {'emb': emb, 'k': 5}):
        print(f'{source} ({d})\n{chunk}\n\n')


@cli.command()
def update_filters():
    """
    Update the filters with new entries.
    """
    import tomlkit
    queries = config['openalex'].get('queries', [])

    filters = [queries[key] for key in queries]
        
    current_date = datetime.datetime.now()

    params = {'email': config['openalex']['email']}
    if config['openalex'].get('api_key'):
        params.update(api_key=config['openalex'].get('api_key'))
        
    for f in filters:
        last_updated = f.get('last_updated', None)  # should be a string or not exist
                
        # this is the first time we run it, so go back two weeks
        if last_updated is None:            
            last_updated = (current_date - datetime.timedelta(weeks=2)).strftime('%Y-%m-%d')

        _filter = f['filter'] + f',from_created_date:{last_updated}'
   
        params.update(filter=_filter)

        next_cursor = '*'
        params.update(cursor=next_cursor)

        while next_cursor:
            data = get_data('https://api.openalex.org/works',
                            params)
            
            next_cursor = data['meta']['next_cursor']
            params.update(cursor=next_cursor)
            for work in tqdm(data['results']):
                wid = work['id']
                if not db.execute('''select source from sources where source = ?''',
                      [wid]).fetchone():
                    text = get_text(work)
                    print(wid, text)
                    add_source(wid, text, work)
        f['last_updated'] = current_date.strftime('%Y-%m-%d')
        
        with open(root / CONFIG, 'w') as f:
            f.write(tomlkit.dumps(config))
       

@cli.command()
def about():
    """Summary statistics of your db.
    """
    nsources, = db.execute('select count(*) from sources').fetchone()
    nchunks, = db.execute('select count(*) from chunks').fetchone()
    print(f'You have {nsources} sources, and {nchunks} chunks')
    print(config)
    


if __name__ == '__main__':
    cli()
    
