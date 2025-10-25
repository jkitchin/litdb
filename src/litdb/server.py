"""Litdb server

This module is for running a REST API server for litdb. This will enable external applications to work with litdb via HTTP requests.

provides:

/add/{src}
/vsearch
/fulltext
"""

from fastapi import FastAPI
import uvicorn
from pydantic import BaseModel


app = FastAPI()


@app.get("/")
async def root():
    return {"message": "litdb server is running!"}


class QueryRequest(BaseModel):
    query: str


@app.post("/vsearch")
async def vsearch(req: QueryRequest):
    return {"message": f"Vector search: {req.query}!"}


def main(port=8000):
    """Start Uvicorn with the chosen port."""
    uvicorn.run("litdb.server:app", host="0.0.0.0", port=port, reload=True)


if __name__ == "__main__":
    main()
