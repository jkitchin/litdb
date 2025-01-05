import os

import numpy as np
import ollama
from rich import print as richprint
from sentence_transformers import SentenceTransformer

from .utils import get_config
from .db import get_db


def gpt():
    """Start a LitGPT chat session.

    If the prompt starts with > the rest of the prompt will be run as a shell
    command. Use this to add references, citations, etc, during the chat.

    If the prompt is

    !save it will save the chat to a file.
    !restart will reset the messages and restart the chat
    """

    config = get_config()
    db = get_db()
    model = SentenceTransformer(config["embedding"]["model"])

    gpt = config.get("gpt", {"model": "llama2"})
    gpt_model = gpt["model"]

    messages = []

    while prompt := input("LitGPT (Ctrl-d to quit)> "):
        if prompt.startswith(">"):
            # This means run the rest of the prompt as a shell command
            # > litdb add some-id
            os.system(prompt[1:].strip())

        elif prompt.startswith("!"):
            # a little sub-language of commands
            if prompt == "!save":
                with open(input("Filename (chat.txt): ") or "chat.txt", "w") as f:
                    for message in messages:
                        f.write(f'{message["role"]}: {message["content"]}\n\n')
            elif prompt == "!restart":
                messages = []
                print("Reset the chat.")

            elif prompt == "!help":
                print("""If the prompt starts with >, run the rest as a shell command, e.g.
> litdb fulltext kitchin

The following subcommands can be used:

!save to save the chat to a file
!restart to reset the chat
!help for this message                
""")

        else:
            emb = model.encode([prompt]).astype(np.float32).tobytes()
            data = db.execute(
                """select sources.text, json_extract(sources.extra, '$.citation')
    from vector_top_k('embedding_idx', ?, 3)
    join sources on sources.rowid = id""",
                (emb,),
            ).fetchall()

            rag_content = ""
            for doc, citation in data:
                rag_content += f"\n\n{doc}"

            messages += [
                {
                    "role": "system",
                    "content": (
                        "Only use the following information to respond"
                        " to the prompt. Do not use anything else:"
                        f" {rag_content}"
                    ),
                }
            ]

            messages += [{"role": "user", "content": prompt}]

            output = ""
            response = ollama.chat(model=gpt_model, messages=messages, stream=True)
            for chunk in response:
                output += chunk["message"]["content"]
                richprint(chunk["message"]["content"], end="", flush=True)

            messages += [{"role": "assistant", "content": output}]

            richprint("The text was generated using these references:\n")
            for i, (text, citation) in enumerate(data, 1):
                richprint(f"{i:2d}. {citation}\n")
