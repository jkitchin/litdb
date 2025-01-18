"""The gpt command for litdb."""

import os
import readline
import subprocess

import numpy as np
import ollama
from rich import print as richprint
from sentence_transformers import SentenceTransformer

from .utils import get_config
from .db import get_db

# Enable command history
readline.parse_and_bind("tab: complete")
readline.parse_and_bind("set editing-mode emacs")

# Disable parallelism in tokenizers
os.environ["TOKENIZERS_PARALLELISM"] = "false"


def gpt():
    """Start a LitGPT chat session. The prompt is interactive.

    If the prompt starts with > the rest of the prompt will be run as a shell
    command. Use this to add references, citations, etc, during the chat.

    If the prompt starts with < the rest of the prompt will be run as a shell
    command and the output used for RAG.

    !save it will save the chat to a file.
    !restart will reset the messages and restart the chat
    !messages will output the current chat history to the shell
    !help to print a help message

    Use Ctrl-d to exit.
    """
    config = get_config()
    db = get_db()
    model = SentenceTransformer(config["embedding"]["model"])

    gpt = config.get("gpt", {"model": "llama2"})
    gpt_model = gpt["model"]

    messages = []

    while prompt := input("LitGPT (Ctrl-d to quit)> "):
        rag_content = ""

        if prompt == "!help":
            print("""\
If the prompt starts with >, run the rest as a shell command, e.g.
> litdb add doi
then continue to a new prompt.

If the prompt starts with < run the shell command but capture the output as
context for the next prompt.

The following subcommands can be used:

!save to save the chat to a file
!restart to reset the chat
!help for this message
""")
            continue

        elif prompt.startswith(">"):
            # This means run the rest of the prompt as a shell command
            # > litdb add some-id
            os.system(prompt[1:].strip())
            continue

        # a little sub-language of commands
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

        # Run shell command to get rag content
        elif prompt.startswith("<"):
            # Some command that outputs text to stdout
            result = subprocess.run(
                prompt[1:].strip(), shell=True, text=True, capture_output=True
            )
            rag_content = f"{prompt[1:]}\n\n" + result.stdout
            prompt = input("LitGPT (Ctrl-d to quit)> ")

        data = None
        if not rag_content:
            # RAG by vector search
            emb = model.encode([prompt]).astype(np.float32).tobytes()
            data = db.execute(
                """\
    select sources.text, json_extract(sources.extra, '$.citation')
    from vector_top_k('embedding_idx', ?, 3)
    join sources on sources.rowid = id""",
                (emb,),
            ).fetchall()

            for doc, citation in data:
                rag_content += f"\n\n{doc}"

        messages += [
            {
                "role": "system",
                "content": (
                    "Only use the following information and previously"
                    " provided information to respond"
                    " to the prompt. Do not use anything else:"
                    f" {rag_content}"
                ),
            }
        ]

        # I think we need to send this before we can use it for the user.
        response = ollama.chat(model=gpt_model, messages=messages, stream=True)
        for chunk in response:
            richprint(chunk["message"]["content"], end="", flush=True)

        messages += [{"role": "user", "content": prompt}]

        output = ""
        # This lets you Ctrl-c to stop streaming if it has gone way off.
        try:
            response = ollama.chat(model=gpt_model, messages=messages, stream=True)
            for chunk in response:
                output += chunk["message"]["content"]
                richprint(chunk["message"]["content"], end="", flush=True)
        except KeyboardInterrupt:
            response.close()
        richprint()

        messages += [{"role": "assistant", "content": output}]

        # We don't always have data here, if you use your own rag data
        if data:
            richprint("\nThe text was generated using these references:\n")
            for i, (text, citation) in enumerate(data, 1):
                richprint(f"{i:2d}. {citation}\n")
