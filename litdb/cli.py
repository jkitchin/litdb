"""CLI for litdb

The main command is litdb. There are subcommands for the actions.
"""

import click
from rich import print
import os
from sentence_transformers import SentenceTransformer
import bs4
import requests
import datetime

from tqdm import tqdm
import datetime
import numpy as np
import ollama
import time
import webbrowser

from . import root, CONFIG, config
from .db import get_db, add_source, add_work, add_author, update_filter, add_bibtex
from .openalex import get_data

db = get_db()

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
    """Add WIDS to the db.

    SOURCES can be one or more of a doi or orcid, a pdf path, a url, bibtex
    file, or other kind of file assumed to be text.

    These are one time additions. 

    """
    for source in tqdm(sources):

        # a work
        if 'doi.org' in source:
            add_work(source, references, citing, related)

        # works from an author
        elif 'orcid' in source:
            add_author(source)

        # a bibtex file
        elif source.endswith('.bib'):
            add_bibtex(source)
            

        # # pdf
        # elif source.endswith('.pdf'):
        #     import litdb.pdf
        #     litdb.pdf.add_pdf(source)

        # # docx
        # elif source.endswith('.docx'):
        #     from docx import Document
        #     doc = Document(source)
        #     add_source(source, '\n'.join([para.text for para in doc.paragraphs]))

        # # pptx
        # elif source.endswith('.pptx'):
        #     from pptx import Presentation
        #     prs = Presentation(source)
        #     text = []
        #     for slide in prs.slides:
        #         for shape in slide.shapes:
        #             if hasattr(shape, "text"):
        #                 text.append(shape.text)
        #     add_source(source, '\n'.join(text))

        # # a url
        # elif source.startswith('http'):
        #     soup = bs4.BeautifulSoup(requests.get(source).text)
        #     add_source(source, soup.get_text())


        # # assume it is text
        # else:            
        #     with open(source) as f:
        #         text = f.read()
        #     add_source(source, text)



#############
# Searching #
#############
      
@cli.command()
@click.argument('query', nargs=-1)
@click.option('-n',  default=3)
def vsearch(query, n=3):
    query = ' '.join(query)
    model = SentenceTransformer(config['embedding']['model'])
    emb = model.encode([query]).astype(np.float32).tobytes()
    c = db.execute('''select sources.source, sources.text, vector_distance_cos(?, embedding) from vector_top_k('embedding_idx', ?, ?)
    join sources on sources.rowid = id''',
    (emb, emb, n))
    for i, row in enumerate(c.fetchall()):
        source, text, similarity = row
        print(f'{i + 1:2d}. ({similarity:1.2f}) {text}\n\n')

        
@cli.command()
@click.argument('query')
@click.option('-n',  default=3)
def fulltext(query, n):
    """Perform a fulltext search on litdb.
    """
    for source, text in db.execute('''select source, text
    from fulltext
    where text match ? order by rank limit ?''',
    (query, n)).fetchall():
        print(f"[link]{source}[/link]")
        print(text + '\n')

        
# Adapted from https://www.arsturn.com/blog/understanding-ollamas-embedding-models
@cli.command()
@click.argument('prompt', nargs=-1)
def gpt(prompt):
    """Run an ollama query with PROMPT.
    """
    t0 = time.time()
    prompt = ' '.join(prompt)
    model = SentenceTransformer(config['embedding']['model'])
    emb = model.encode([prompt]).astype(np.float32).tobytes()
    print(f'It took {time.time() - t0:1.1f} sec to embed the prompt')
    t0 = time.time()
    data = db.execute('''select sources.text from vector_top_k('embedding_idx', ?, 3) join sources on sources.rowid = id''',
    (emb,)).fetchall()
    print(f'It took  {time.time() - t0:1.1f} sec to get the top three docs')
    t0 = time.time()
    output = ollama.generate(model="llama2", prompt=f"Using data: {data}. Respond to the prompt: {prompt}")
    print(output['response'])
    print(f'It took  {time.time() - t0:1.1f} sec to generate and print the response.')

    print('The text was generated using these references')
    for i, result in enumerate(data):
        print('f{i:2d}. {result}\n')        


###########
# Filters #
###########

@cli.command()
@click.argument('filter')
@click.option('-d', '--description')
def add_filter(filter, description=None):
    """Add an OpenAlex FILTER. 
    """
    db.execute('insert into queries(filter, description) values (?, ?)',
               (filter, description))
    db.commit()

    
@cli.command()
@click.argument('filter')
def rm_filter(filter):
    """Remove an OpenAlex FILTER. 
    """
    db.execute('delete from queries where filter = ?',
               (filter,))
    db.commit()


@cli.command()
def update_filters():
    """Update litdb using a filter with works from a created date.
    """
    filters = db.execute('''select filter, last_updated from queries''')
    for f, last_updated in filters.fetchall():
        update_filter(f, last_updated)


@cli.command()        
def list_filters():
    """List the filters.
    """
    filters = db.execute('''select rowid, filter, description, last_updated from queries''')
    for rowid, f, description, last_updated in filters.fetchall():
        print(f'{rowid:3d}. {description:30s} : {f} ({last_updated})')

        
########################################
# Convenience functions to add filters #
########################################
        
@cli.command()
@click.argument('name', nargs=-1)
def author_search(name):
    """Search OpenAlex for name.
    Uses the autocomplete endpoint to find an author's orcid.
    """
    auname = ' '.join(name)
    
    url = 'https://api.openalex.org/autocomplete/authors'

    from .openalex import get_data

    data = get_data(url,
                    params={'q': auname})

    for result in data['results']:
        print(f'- {result["display_name"]}\n  {result["hint"]} {result["external_id"]}\n\n')


@cli.command()
@click.argument('orcid')
@click.option('-r', '--remove', is_flag=True, help='remove')
def follow(orcid, remove=False):
    """Add a filter to follow orcid.
    """

    if not orcid.startswith('http'):
        orcid = f'https://orcid.org/{orcid}'

    # Seems like we should get their articles first.
    add_author(orcid)

    f = f'author.orcid:{orcid}'

    if remove:
        c = db.execute('''delete from queries where  filter = ?''',
                   (f,))
        db.commit()
        print(f'{c.rowcount} rows removed')
        return
        
    url = f'https://api.openalex.org/authors/{orcid}'
    data = get_data(url)
    name = data['display_name']  
    
    db.execute('''insert or ignore into queries(filter, description) values (?, ?)''',
               (f, name))
    print(f'Following {name}: {orcid}')
    db.commit()


@cli.command()
@click.argument('query', nargs=-1)
@click.option('-r', '--remove', is_flag=True, help='remove')
def watch(query, remove=False):
    """Setup a watch on query.
    QUERY: string, a filter for openalex.
    """
    
    # First, we should make sure the filter is valid
    query = ' '.join(query)

    if remove:
        c = db.execute('''delete from queries where filter = ?''', (query,))
        db.commit()
        print(f'{c.rowcount} rows removed')
        return
    
    url = 'https://api.openalex.org/works'

    data = get_data(url, params={'filter': query})
    if len(data['results']) == 0:
        print(f"Sorry, {query} does not seem valid.")

    if remove:
        c = db.execute('delete from queries where filter = ?''', (query,))        
        print('Deleted {c.rowcount} rows')
        db.commit()
    else:
        c = db.execute('''insert or ignore into queries(filter, description) values (?, ?)''',
                       (query,))        
        print(f'Added {c.rowcount} rows')
        db.commit()
        print(f'Watching {query}')
    

@cli.command()
@click.argument('doi')
@click.option('-r', '--remove', is_flag=True, help='remove')
def citing(doi, remove=False):
    """Setup a watch for articles that cite doi.
    """
           
    url = 'https://api.openalex.org/works'

    # We need an OpenAlex id
    f = f'doi:{doi}'

    data = get_data(url, params={'filter': f})
    if len(data['results']) == 0:
        print(f"Sorry, {doi} does not seem valid.")

    wid = data['results'][0]['id']

    if remove:
        c = db.execute('''delete from queries where filter = ?''',
                   (f'cites:{wid}',))
        db.commit()
        print(f'Deleted {c.rowcount} rows')
    else:
        c = db.execute('''insert or ignore into queries(filter, description) values (?, ?)''',
               (f'cites:{wid}', f'Citing papers for {doi}'))
        
        db.commit()
        print(f'Added {c.rowcount} rows')
    

@cli.command()
@click.argument('doi')
@click.option('-r', '--remove', is_flag=True, help='remove')
def related(doi, remove=False):
    """Setup a watch for articles that are related to doi.
    """
           
    url = 'https://api.openalex.org/works'

    # We need an OpenAlex id
    f = f'doi:{doi}'

    data = get_data(url, params={'filter': f})
    if len(data['results']) == 0:
        print(f"Sorry, {doi} does not seem valid.")

    wid = data['results'][0]['id']

    if remove:
        c = db.execute('''delete from queries where filter = ?''',
                   (f'related_to:{wid}',))
        db.commit()
        print(f'Deleted {c.rowcount} rows')
    else:
        c = db.execute('''insert or ignore into queries(filter, description) values (?, ?)''',
               (f'related_to:{wid}', f'Related papers for {doi}'))
        
        db.commit()
        print(f'Added {c.rowcount} rows')        


#############
# Utilities #
#############
        
@cli.command()
@click.argument('sources', nargs=-1)
def bibtex(sources):
    """Generate bibtex entries for sources."""

    from .bibtex import dump_bibtex
    import json
    for source in sources:
        work, = db.execute('''select extra from sources where source = ?''', (source,)).fetchone()
        print(dump_bibtex(json.loads(work)))


@cli.command()
@click.argument('sources', nargs=-1)
def citation(sources):
    """Generate citation strings for sources."""

    from .bibtex import dump_bibtex
    import json
    for i, source in enumerate(sources):
        citation, = db.execute('''select json_extract(extra, '$.citation') from sources where source = ?''', (source,)).fetchone()
        print(f'{i + 1:2d}. {citation}') 

@cli.command()
def about():
    """Summary statistics of your db.
    """
    nsources, = db.execute('select count(source) from sources').fetchone()    
    print(f'You have {nsources} sources')

    
@cli.command()
@click.argument('sql')
def sql(sql):
    """Run the SQL command on the db.
    """
    for row in db.execute(sql).fetchall():
        print(row)


@cli.command()
def visit(source):
    

    if source.startswith('http'):
        webbrowser.open(source, new=2)
    
        
if __name__ == '__main__':
    cli()
    
