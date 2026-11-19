"""LitGPT using litellm."""

import importlib
import logging
import os
import pydoc
import re
import readline
import subprocess
import warnings

import litellm
import numpy as np
from docling.document_converter import DocumentConverter
from litellm import completion
from rich import print as richprint

# Try to import backoff (optional dependency in crawl extra)
try:
    import backoff
except ImportError:
    # Create a no-op decorator if backoff is not available
    class backoff:
        @staticmethod
        def on_exception(*args, **kwargs):
            def decorator(func):
                return func

            return decorator

        expo = None
        full_jitter = None


from .audio import get_audio_text, record
from .db import get_db, get_model
from .utils import get_config

warnings.filterwarnings("ignore")

# Enable command history
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set editing-mode emacs")

# Errors worth retrying; others (bad key, bad model name, ...) fail right away.
TRANSIENT_ERRORS = (
    litellm.RateLimitError,
    litellm.APIConnectionError,
    litellm.Timeout,
    litellm.ServiceUnavailableError,
    litellm.InternalServerError,
)


def load_prompt_history(db):
    """Load previous prompts from DB into the readline history."""
    for (prompt,) in db.execute(
        "select prompt from prompt_history order by rowid"
    ).fetchall():
        readline.add_history(prompt)


# Disable parallelism in tokenizers
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Suppress docling logging output
logging.getLogger("docling").setLevel(logging.CRITICAL)


def get_docstring_from_name(name):
    """Return the docstring for the dotted Python NAME, or None if not found."""
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
        return None


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
    except Exception:  # noqa: BLE001 - docling raises many types; fall back to text
        with open(os.path.expanduser(path)) as f:
            return f.read()


def expand_prompt(prompt):
    """Expand the prompt.

    There is some fancy syntax I support.

    [[file/url]] gets replaced by text representing that.

    `numpy.linspace` gets replaced by the docstring describing it.

    <text to the end of the line
    """
    # All three are expanded in one pass over what the user typed, so text that
    # comes from a file, url, docstring or command is never expanded itself. A
    # web page with a line starting with < must not run a shell command.
    return EXPANSION.sub(_expand_match, prompt)


EXPANSION = re.compile(
    r"\[\[(?P<path>[^\[\]]*)\]\]|`(?P<name>[^`]*)`|^<(?P<cmd>.+)$", re.MULTILINE
)
PYTHON_NAME = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")


def _expand_match(m):
    """Return the expansion of one EXPANSION match M."""
    if (path := m["path"]) is not None:
        try:
            return process_file_url(path.strip())
        except OSError as e:
            richprint(f"[red]Could not read {path}: {e}[/red]")
            return m[0]

    if (name := m["name"]) is not None:
        # Only dotted names like numpy.linspace; other `code` is left alone.
        if PYTHON_NAME.match(name.strip()):
            doc = get_docstring_from_name(name.strip())
            if doc is not None:
                return doc
            richprint(f"[yellow]No docstring found for {name}.[/yellow]")
        return m[0]

    result = subprocess.run(
        m["cmd"].strip(), shell=True, text=True, capture_output=True, check=False
    )
    return result.stdout


def get_rag_content(prompt, n):
    """Return data from litdb using prompt."""
    config = get_config()
    db = get_db()
    model = get_model(config["embedding"]["model"])

    emb = model.encode([prompt]).astype(np.float32).tobytes()
    data = db.execute(
        """\
    select sources.source, sources.text, json_extract(sources.extra, '$.citation')
    from vector_top_k('embedding_idx', ?, ?)
    join sources on sources.rowid = id""",
        (emb, int(n)),
    ).fetchall()

    rag_content = ""
    references = ""

    for i, (source, doc, citation) in enumerate(data, 1):
        rag_content += f"\n\n<citation>{citation}</citation>\n\n{doc}"
        references += f"{i:2d}. {citation or source}\n"

    return rag_content, references


@backoff.on_exception(
    backoff.expo,  # Exponential backoff strategy
    TRANSIENT_ERRORS,  # Exception(s) to catch
    max_tries=5,  # Maximum number of retries
    jitter=backoff.full_jitter,  # Helps distribute retry attempts
)
def get_completion(model, messages, max_tokens=None):
    """Return the output from model for the list of messages.

    Args:
        model: a string for the LiteLLM model.
        messages: a list of dictionaries defining the messages.
        max_tokens: optional max tokens for completion (defaults to model default)

    Returns:
        the completion output.
    """
    output = ""
    # This lets you Ctrl-c to stop streaming if it has gone way off.
    try:
        kwargs = {"model": model, "messages": messages, "stream": True}
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens

        response = completion(**kwargs)
        for chunk in response:
            out = chunk.choices[0].delta.content or ""
            richprint(out, end="")
            output += out

    except KeyboardInterrupt:
        pass
    except AttributeError as e:
        # Suppress litellm TranscriptionCreateParams.__annotations__ errors
        if "__annotations__" not in str(e):
            raise

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
    load_prompt_history(db)

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

        try:
            prompt = _read_prompt()
        except EOFError:
            print()
            return

        if debug:
            print(f"Starting with prompt: {prompt}")

        db.execute("""insert into prompt_history(prompt) values (?)""", (prompt,))
        db.commit()

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
                f.writelines(
                    f"{message['role']}: {message['content']}\n\n"
                    for message in messages
                )
            continue

        elif prompt == "!restart":
            messages = []
            print("Reset the chat.")
            continue

        elif prompt == "!messages":
            for message in messages:
                richprint(f"{message['role']}: {message['content']}\n\n")
            continue

        elif prompt == "":
            if debug:
                print("Recording")

            prompt = get_audio_text(record())
            print(prompt + "\n\n")

        else:
            prompt = expand_prompt(prompt)

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

        # Only the current turn carries the retrieved documents. Keeping them in
        # the history would add several full papers per turn and soon overflow
        # the context window.
        question = prompt
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

        output = get_completion(
            gpt_model, [*messages, {"role": "user", "content": prompt}]
        )

        richprint()

        messages += [
            {"role": "user", "content": question},
            {"role": "assistant", "content": output},
        ]

        # We don't always have data here, if you use your own rag data

        # if references:
        #    richprint("References:\n\n" + references)


def _read_prompt():
    """Read a prompt; lines ending in a backslash continue on the next line."""
    lines = [input("\033[1;34mLitGPT (Ctrl-d to quit, enter for mic)> \033[0m")]
    while lines[-1].endswith("\\"):
        lines[-1] = lines[-1][:-1]
        lines.append(input())
    return "\n".join(lines)
