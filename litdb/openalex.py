"""OpenAlex plugin for litdb.
"""

import litdb.db as db

from litdb import config

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

from ratelimit import limits
from tqdm import tqdm

# limit openalex calls to 10 per second
@limits(calls=10, period=1)
def get_data(url, params):
    """Get json data for URL and PARAMS with rate limiting. If this request
    fails, it prints the status code, but returns an empty dictionary.

    """
    try:
        retry = Retry(
            total=5,
            backoff_factor=2,
            status_forcelist=[429, 500, 502, 503, 504])

        adapter = HTTPAdapter(max_retries=retry)

        session = requests.Session()
        session.mount('https://', adapter)
        req = session.get(url, params=params, timeout=180)

        if req.status_code == 200:
            return req.json()
        else:
            print('status code: ', req.status_code)
            print('text: ', req.text)
            print('url: ', req.url)
            return {'meta': {'next_cursor': None},
                    'results':[]}
    
    except Exception as e:
        print(e)


def html_to_text(html_string):
    """Strip html from html_string."""
    if html_string:
        soup = BeautifulSoup(html_string, 'html.parser')
        return soup.get_text()
    else:
        return html_string

    
def get_text(result):
    """Return a rendered text represenation for RESULT.
    """
    aii = result.get('abstract_inverted_index', None)
    word_index = []
    
    if aii:
        for k,v in aii.items():
            for index in v:
                word_index.append([k, index])

        word_index = sorted(word_index,key = lambda x : x[1])
        abstract = ' '.join([x[0] for x in word_index])
    else:
        abstract = 'No abstract'

    abstract = html_to_text(abstract)
    title = result.get('display_name', '') or 'No title'
    year = result.get('publication_year', None)
    wid = result['id']
    authors = ', '.join([au['author']['display_name'] for au in result['authorships']])
    source = result.get('primary_location', {}).get('source', {})
    if source:
        host = source.get('display_name', 'No host')
    else:
        host = 'No host'

    return f'{title}, {authors}, {host} ({year}) {wid}\n\n{abstract}'
    

def add_author(oaid):
    """Add all works from an author.
    "id": "https://openalex.org/A5003442464",
    "orcid": "https://orcid.org/0000-0003-2625-9232",
    """
    aurl = 'https://api.openalex.org/authors/' + oaid
    params = {'email': config['openalex']['email']}
    if config['openalex'].get('api_key'):
        params.update(api_key=config['openalex'].get('api_key'))

    data = get_data(aurl, params)

    wurl = data["works_api_url"]
    next_cursor = '*'
    params.update(cursor=next_cursor)
    while next_cursor:
        wdata = get_data(wurl, params)
        next_cursor = wdata['meta']['next_cursor']
        params.update(cursor=next_cursor)
        for work in tqdm(wdata['results']):
            add_work(work['id'])

    
def add_work(workid, references=False, citing=False, related=False):
    """Add a single work to litdb.

    workid is the OpenAlex ID, or a doi (full url).

    if references is truthy, also add them.
    if citing is truthy, also add them.
    if related is truthy, also add them.
    """

    params = {'email': config['openalex']['email']}
    if config['openalex'].get('api_key'):
        params.update(api_key=config['openalex'].get('api_key'))

    data = get_data('https://api.openalex.org/works/' + workid, params)

    # I standardize on the OpenAlex work id. I don't love that because DOI is
    # easier to work with. The upside is it is canonical, and avoids duplicate
    # entries with DOI and OpenAlex ID.
    source = data.get('id', None)
    if source is None:
        # I guess this could happen for a bad DOI.
        print(f'No id found for {workid}.\n{data}')
        return

    # Only add if we don't have this one
    if not db.db.execute('''select source from sources where source = ?''',
                      [source]).fetchone():       
        db.add_source(source, get_text(data), data)

    if references:
        for wid in tqdm(data['referenced_works']):
            # skip ones we have
            if db.db.execute('''select source from sources where source = ?''',
                      [wid]).fetchone():
                continue
            print(f'reference {wid}', db.db.execute('''select source from sources where source = ?''',
                      [wid]).fetchone())
            rdata = get_data('https://api.openalex.org/works/' + wid, params)
            source = rdata['id']
            # I don't know if I need [SEP] here. I have seen some models do this.
            text = get_text(rdata)
            try:
                db.add_source(source, text, rdata)
            except:
                print(f'Failed to add {source}')

    if related:
        for wid in tqdm(data['related_works']):
            # skip ones we have
            if db.db.execute('''select source from sources where source = ?''',
                          [wid]).fetchone():
                continue
            print(f'related {wid}')
            rdata = get_data('https://api.openalex.org/works/' + wid, params)
            source = rdata['id']
            text = get_text(rdata)
            try:
                db.add_source(source, text, rdata)
            except:
                print(f'Failed to add {source}')

    if citing:
        CURL = data['cited_by_api_url']
        next_cursor = '*'
        params.update(cursor=next_cursor)
        while next_cursor:
            cdata = get_data(CURL, params)
            next_cursor = cdata['meta']['next_cursor']
            params.update(cursor=next_cursor)
            for work in tqdm(cdata['results']):
                source = work['id']
                if db.db.execute('''select source from sources where source = ?''',
                          [source]).fetchone():
                    continue
                print(f'citing {source}')
                text = get_text(work)
                try:
                    db.add_source(source, text, work)
                except:
                    print(f'Failed to add {source}')


def update_filters(since):
    """Update works filters from the since date (%Y-%m-%d)."""
    wurl = 'https://api.openalex.org/works'
    for _filter in config['openalex']['filters']:
        _filter += f',from_created_date:{since}'

        params = {'email': config['openalex']['email'],
                  'filter': _filter}
        if config['openalex'].get('api_key'):
            params.update(api_key=config['openalex'].get('api_key'))

        next_cursor = '*'
        params.update(cursor=next_cursor)
        while next_cursor:
            data = get_data(wurl, params)
            next_cursor = data['meta']['next_cursor']
            params.update(cursor=next_cursor)
            print(f'Found {data["meta"]["count"]} results.')
            for work in tqdm(data['results']):
                add_work(work['id'])

        
if __name__ == '__main__':
    add_work('http://dx.doi.org/10.1021/jacs.4c01353',
             references=True, citing=True,
             related=True)
    

    
