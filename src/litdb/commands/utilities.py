"""Utility commands for litdb.

Commands:
- web: Open web searches across multiple platforms
- audio: Record audio and convert to vector search
- chat: Interactive chat with litdb using LLM
- app: Launch Streamlit web app
- version: Show litdb version
- coa: Generate NSF Collaborators and Other Affiliations table
"""

import os

import click
import webbrowser

from ..audio import get_audio_text, record
from ..chat import chat
from . import search


@click.command()
@click.argument("query", nargs=-1)
@click.option("-g", "--google", is_flag=True)
@click.option("-gs", "--google-scholar", is_flag=True)
@click.option("-pm", "--pubmed", is_flag=True)
@click.option("-ar", "--arxiv", is_flag=True)
@click.option("-cr", "--chemrxiv", is_flag=True)
@click.option("-br", "--biorxiv", is_flag=True)
@click.option("-a", "--all", is_flag=True)
def web(query, google, google_scholar, pubmed, arxiv, chemrxiv, biorxiv, all):
    """Open a web search for QUERY.

    We always do an OpenAlex search.

    If these are true, we also search here
    GOOGLE
    GOOGLE_SCHOLAR
    PUBMED
    ARXIV
    CHEMRXIV
    BIORXIV
    """
    query = " ".join(query)

    if all:
        google, google_scholar = (
            True,
            True,
        )
        pubmed, arxiv, chemrxiv, biorxiv = True, True, True, True

    # This is to avoid some huggingface/tokenizer warning. I don't know why we
    # need to do it, but this code forks the process, and triggers that warning.
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    oa = f"https://openalex.org/works?filter=default.search:{query}"
    webbrowser.open(oa)

    if google:
        url = f"https://www.google.com/search?q={query}"
        webbrowser.open(url)

    if google_scholar:
        url = f"https://scholar.google.com/scholar?q={query}"
        webbrowser.open(url)

    if pubmed:
        url = f"https://pubmed-ncbi-nlm-nih-gov.cmu.idm.oclc.org/?term={query}"
        webbrowser.open(url)

    if arxiv:
        url = f"https://arxiv.org/search/?query={query}"
        webbrowser.open(url)

    if chemrxiv:
        url = f"https://chemrxiv.org/engage/chemrxiv/search-dashboard?text={query}"
        webbrowser.open(url)

    if biorxiv:
        url = f"https://www.biorxiv.org/search/{query}"
        webbrowser.open(url)


@click.command()
@click.option("-p", "--playback", is_flag=True, help="Play audio back")
def audio(playback=False):
    """Record audio, convert it to text, and do a vector search on the text.

    The idea is nice, but the quality of transcription for scientific words is
    not that great. A better transcription library might make this more useful.
    """

    while True:
        afile = record()
        text = get_audio_text(afile)
        print("\n" + text + "\n")

        if playback:
            import playsound

            playsound.playsound(afile, block=True)

        response = input("Is that what you want to search? ([y]/n/q): ")
        if response.lower().startswith("q"):
            return
        elif response.lower().startswith("n"):
            # record a new audio
            continue
        else:
            # move on to searching
            break

    search.vsearch.callback([text])


@click.command(help=chat.__doc__)
@click.option("--model", default=None, help="The LiteLLM model to use.")
@click.option("--debug", is_flag=True, default=False)
def chat_command(model, debug):
    """Interactive chat with litdb using LiteLLM."""
    chat(model, debug)


@click.command()
def app():
    """Launch the Streamlit app in the default web browser."""
    dirname = os.path.dirname(os.path.dirname(__file__))
    app_path = os.path.join(dirname, "app.py")
    os.system(f"streamlit run {app_path}")


@click.command()
def version():
    """Print the version of litdb."""
    import pkg_resources

    version = pkg_resources.get_distribution("litdb").version
    print(f"Litdb: version {version}")


@click.command()
@click.argument("orcid")
def coa(orcid):
    """Generate Table 4 of Collaborators and Other Affiliations for NSF.

    ORCID is an orcid URL for the user to generate the table for.
    The file is saved in {orcid}-{today}.xlsx.
    """
    from ..coa import get_coa

    get_coa(orcid)
