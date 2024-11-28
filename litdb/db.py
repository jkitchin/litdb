"""Setup and add things to the database.

"""
import json
import time
import sqlite3
import sqlite_vec

from litdb import root, config

import numpy as np
from sentence_transformers import SentenceTransformer
from langchain.text_splitter import RecursiveCharacterTextSplitter

model = SentenceTransformer(config['embedding']['model'])

splitter = RecursiveCharacterTextSplitter(chunk_size=config['embedding']['chunk_size'],
                                          chunk_overlap=config['embedding']['chunk_overlap'])

DB = root / config['database']['db']
db = sqlite3.connect(DB)
db.enable_load_extension(True)
sqlite_vec.load(db)
db.enable_load_extension(False)

db.execute('PRAGMA foreign_keys = ON')
db.execute('PRAGMA journal_mode=WAL')

# SOURCES
db.execute("""create table if not exists
sources(rowid integer primary key autoincrement,
source text unique,
text text,
extra text,
date_added text)""")

# FULL TEXT
db.execute("""create virtual table if not exists
fulltext using fts5(source, text)""")

# CHUNKS
db.execute("""create table if not exists
chunks(rowid integer primary key autoincrement,
sourceid,
chunk text,
foreign key(sourceid) references sources(rowid) on delete cascade)""")

# EMBEDDINGS
db.execute(f"""create virtual table if not exists
embeddings USING vec0(embedding float[{config['embedding']['embedding_size']}])""")


def add_source(source, text, extra=None):
    """Add the text from source to the database.
    extra is a dictionary of additional information you might want to include.

    source is a string that ideally allows you to open it, e.g. a path, url,
    etc.

    text: the full text associated with source. It should already be sanitized,
    e.g. remove html tags, etc.

    extra: something jsonable. The main idea is the data from OpenAlex, but you
    can use this for other metadata. It is stored as a json string.

    """
    # add the source, text and extra to SOURCES
    with db:
        if db.execute('''select source from sources where source = :source''',
                      dict(source=source)).fetchone():
            print(f'we already have {source}')
            return                      
        
        c = db.execute('''insert into sources(source, text, extra, date_added)
        values(:source, :text, :extra, :date_added)''',
        {'source': source,
         'text': text,
         'extra': json.dumps(extra),
         'date_added': time.asctime()})
        sourceid = c.lastrowid
        
        # add text to the fts5 virtual table
        db.execute('''insert into fulltext values(:source, :text)''',
        dict(source=source, text=text))

        # chunk the text and get embeddings for each one
        chunks = splitter.split_text(text)
        embeddings = model.encode(chunks)
        
        # add chunks to the CHUNKS table and embeddings to the EMBEDDINGS table.
        for chunk, embedding in zip(chunks, embeddings):
            c = db.execute('''insert into chunks(sourceid, chunk)
            values(:sourceid, :chunk)''',
            dict(sourceid=sourceid, chunk=chunk))
            chunkid = c.lastrowid

            db.execute('''insert into embeddings(rowid, embedding)
            values (:rowid, :embedding)''',
            dict(rowid=chunkid, embedding=embedding.astype(np.float32)))

