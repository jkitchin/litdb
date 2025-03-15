"""LitGPT using litellm."""

import os
import readline
import subprocess

import warnings

import numpy as np
from litellm import completion
from rich import print as richprint
from sentence_transformers import SentenceTransformer

import pydoc
import re
import importlib
from docling.document_converter import DocumentConverter
from docling.exceptions import ConversionError
import logging
import backoff

from .utils import get_config
from .db import get_db
from .audio import record, get_audio_text

warnings.filterwarnings("ignore")

# Enable command history
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set editing-mode emacs")

# Load history
db = get_db()

# This is needed to update existing litdb dbs.
try:
    db.execute("""select prompt from prompt_history order by rowid limit 1""")
except ValueError:
    db.execute(
        """create table if not exists
            prompt_history(rowid integer primary key,
            prompt text)"""
    )

cursor = db.execute("""select prompt from prompt_history order by rowid""")
for (row,) in cursor.fetchall():
    readline.add_history(row)

# Disable parallelism in tokenizers
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Suppress docling logging output
logging.getLogger("docling").setLevel(logging.CRITICAL)


def get_docstring_from_name(name):
    """Try to get a docstring from name."""
    # Try to be a little helpful with these shortcuts.
    if name.startswith("np."):
        name = name.replace("np.", "numpy.")

    if name.startswith("plt."):
        name = name.replace("plt.", "matplotlib.pyplot.")

    try:
        # Dynamically import the module or object
        module_name, obj_name = name.rsplit(".", 1)
        module = importlib.import_module(module_name)
        obj = getattr(module, obj_name)

        # Get the docstring using pydoc
        docstring = pydoc.render_doc(obj, renderer=pydoc.plaintext)
        return docstring
    except (ImportError, AttributeError, ValueError):
        # This does some weird stuff
        # docstring = pydoc.apropos(name)
        return f"Nothing found for {name}. Try using the full python name."


def process_file_url(path):
    """Return text from the path.

    Path may be a url or file.

    These are supported by docling:

    PDF
    DOCX (Microsoft Word)
    PPTX (Microsoft PowerPoint)
    XLSX (Microsoft Excel)
    Images
    HTML
    AsciiDoc
    Markdown

    Other files are assumed to be text and the contents are used.
    """
    try:
        converter = DocumentConverter()
        result = converter.convert(path)

        return result.document.export_to_markdown()
    except ConversionError:
        with open(path) as f:
            return f.read()


def expand_prompt(prompt):
    """Expand the prompt.

    There is some fancy syntax I support.

    [[file/url]] gets replaced by text representing that.

    `numpy.linspace` gets replaced by the docstring describing it.

    <text to the end of the line
    """
    # Expand files/urls
    pattern = r"\[\[([^\[\]]*)\]\]"
    matches = re.findall(pattern, prompt)
    for hit in matches:
        replace = process_file_url(hit)
        prompt = prompt.replace(hit, replace)

    # Expand pydoc
    pattern = r"(`([^`]*)`)"
    matches = re.findall(pattern, prompt)
    for _match, hit in matches:
        replace = get_docstring_from_name(hit)
        prompt = prompt.replace(_match, replace)

    # expand the < commands
    pattern = r"(^<(.+)$)"
    matches = re.findall(pattern, prompt, re.MULTILINE)
    for _match, cmd in matches:
        result = subprocess.run(cmd.strip(), shell=True, text=True, capture_output=True)
        prompt = prompt.replace(_match, result.stdout)

    return prompt


def get_rag_content(prompt, n):
    """Return data from litdb using prompt."""
    config = get_config()
    db = get_db()
    model = SentenceTransformer(config["embedding"]["model"])

    emb = model.encode([prompt]).astype(np.float32).tobytes()
    data = db.execute(
        f"""\
    select sources.source, sources.text, json_extract(sources.extra, '$.citation')
    from vector_top_k('embedding_idx', ?, {n})
    join sources on sources.rowid = id""",
        (emb,),
    ).fetchall()

    rag_content = ""
    references = ""

    for i, (source, doc, citation) in enumerate(data, 1):
        rag_content += f"\n\n<citation>{citation}</citation>\n\n{doc}"
        references += f"{i:2d}. {citation or source}\n"

    return rag_content, references


@backoff.on_exception(
    backoff.expo,  # Exponential backoff strategy
    Exception,  # Exception(s) to catch
    max_tries=5,  # Maximum number of retries
    jitter=backoff.full_jitter,  # Helps distribute retry attempts
)
def get_completion(model, messages):
    """Return the output from model for the list of messages.

    Args:
        model: a string for the LiteLLM model.
        messages: a list of dictionaries defining the messages.

    Returns:
        the completion output.
    """
    output = ""
    # This lets you Ctrl-c to stop streaming if it has gone way off.
    try:
        response = completion(model=model, messages=messages, stream=True)
        for chunk in response:
            out = chunk.choices[0].delta.content or ""
            richprint(out, end="")
            output += out

    except KeyboardInterrupt:
        pass

    return output


def chat(model=None, debug=False):
    """Start a LitGPT chat session using LiteLLM.

    Use these strings to specify the model
    (https://docs.litellm.ai/docs/providers).

    ollama: ollama/llama3.3

    (https://docs.litellm.ai/docs/providers/openai)
    openai: gpt-3.5-turbo, gpt-4o

    (https://docs.litellm.ai/docs/providers/gemini)
    gemini: gemini/gemini-pro
    anthropic: claude-3-haiku-20240307, claude-3-sonnet-20240229

    You should ensure the API_KEYS are stored in your environment.

    Usually in your .bash_profile something like this:

    export OPENAI_API_KEY=...
    export GEMINI_API_KEY=...
    export ANTHROPIC_API_KEY=...
    You don't need to do anything special for ollama.

    The prompt is interactive. If the prompt starts with > the rest of the
    prompt will be run as a shell command. Use this to add references,
    citations, etc, during the chat.

    If the prompt starts with < the rest of the prompt will be run as a shell
    command and the output used for RAG.

    RAG is on by default, but you can turn it off with --norag in the prompt.

    !save will save the chat to a file, you will be prompted for the name.
    !restart will reset the messages and restart the chat.
    !messages will output the current chat history to the shell.
    !help to print a help message.

    There is also some prompt expansion. [[file/url]] will be expanded to the
    text in the file or url. We use docling for this, and otherwise assume they
    are text to be read in.

    You can have text in backticks, e.g. `np.linspace` which is expanded with
    docstrings from Python where possible.

    a line that starts with < is treated like a shell command. That command will
    be run, and the output expanded into the prompt.

    Use Ctrl-d to exit.

    if debug is True, it will print some extra info.

    """
    config = get_config()
    db = get_db()

    if model is None:
        gpt = config.get("llm", {"model": "ollama/llama2"})
        gpt_model = gpt["model"]
    else:
        # You can override this at the cli if you want, e.g.
        # --model=ollama/llama3.3
        gpt_model = model

    richprint(f"Beginning chat with {gpt_model}")

    # we start with no history. Even though you can look up the prompt history,
    # I assume you don't want to start there.
    messages = []

    while True:
        rag = True  # default to using this

        prompt = input("\033[1;34mLitGPT (Ctrl-d to quit, enter for mic)> \033[0m")

        # line continuation
        if prompt.endswith("\\"):
            while next := input():
                prompt += "\n" + next

        if debug:
            print(f"Starting with prompt: {prompt}")

        db.execute("""insert into prompt_history(prompt) values (?)""", (prompt,))
        db.commit()

        prompt = expand_prompt(prompt)

        if prompt == "!help":
            print("""\
If the prompt starts with >, run the rest as a shell command, e.g.
> litdb add doi
then continue to a new prompt.

If the prompt starts with < run the shell command and expand it in the prompt

The following subcommands can be used:

!save to save the chat to a file
!restart to reset the chat
!help for this message
""")
            continue

        elif prompt.startswith(">"):
            # This means run the rest of the prompt as a shell command But don't
            # add anything to the prompt, just go back to get a new prompt. This
            # is just so you don't have to break out of your chat or go to
            # another window
            #
            # > litdb add some-id
            if debug:
                print(f'Running "{prompt[1:].strip()}"')
            os.system(prompt[1:].strip())
            continue

        elif prompt == "!save":
            with open(input("Filename (chat.txt): ") or "chat.txt", "w") as f:
                for message in messages:
                    f.write(f'{message["role"]}: {message["content"]}\n\n')
            continue

        elif prompt == "!restart":
            messages = []
            print("Reset the chat.")
            continue

        elif prompt == "!messages":
            for message in messages:
                richprint(f'{message["role"]}: {message["content"]}\n\n')
            continue

        elif prompt == "":
            if debug:
                print("Recording")

            prompt = get_audio_text(record())
            print(prompt + "\n\n")

        if "--norag" in prompt:
            rag = False
            prompt = prompt.replace("--norag", "")
            if debug:
                print("--norag found in prompt. Turned RAG off.")

        match = re.search(r"--n=(\d+)", prompt)
        if match:
            n = int(match.group(1))
            prompt = prompt.replace(match.group(0), "")
            if debug:
                print(f"Found {match.group(0)}, set n={n}")
        else:
            n = 3

        # Now we do RAG on litdb if needed.
        # I don't use the references below, so we do not assign them.
        if rag:
            rag_content, _ = get_rag_content(prompt, n)
        else:
            rag_content, _ = (None, None)

        if rag and rag_content:
            prompt = f"""You are a professional scientist. Use the following
        retrieved information to respond to the user prompt. Reference the
        citations if you use that information. Each reference is surrounded by
        <citation> tags. If the information is not relevent, do not use it.

        <retrieved information>
        {rag_content}

        <user prompt>
        {prompt}"""

        if debug:
            richprint(f"Use RAG: {rag}")
            richprint(f"PROMPT: {prompt}")

        messages += [{"role": "user", "content": prompt}]

        output = get_completion(gpt_model, messages)

        richprint()

        messages += [{"role": "assistant", "content": output}]

        # We don't always have data here, if you use your own rag data

        # if references:
        #    richprint("References:\n\n" + references)
