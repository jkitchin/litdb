"""Streamlit app for litdb.

This is not as advanced as the terminal option. I don't expand the prompt, for
example.
"""

from litellm import completion
import streamlit as st

from litdb.utils import get_config
from litdb.db import get_db
from litdb.chat import get_rag_content
import os

config = get_config()
db = get_db()

gpt = config.get("llm", {"model": "ollama/llama2"})


dbf = os.path.join(config["root"], "litdb.libsql")


kb = 1024
mb = 1024 * kb
gb = 1024 * mb

(nsources,) = db.execute("select count(source) from sources").fetchone()

st.title("LitGPT")
st.header("Database")
st.markdown(f"""Path: {dbf}

Database size: {os.path.getsize(dbf) / gb:1.2f} GB ({nsources} sources)""")

if "openai_model" not in st.session_state:
    st.session_state["model"] = gpt["model"]

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# This is the main loop
if prompt := st.chat_input("What would you like to know? "):
    # This mirrors what you wrote. We do this before expanding it
    with st.chat_message("user"):
        st.markdown(prompt)

    rag_content, references = get_rag_content(prompt, 3)

    prompt = f"""Use the following retrieved information to respond to
        the user prompt. Reference the citations if you use that information.

        <retrieved information>
        {rag_content}

        <user prompt>
        {prompt}"""

    st.session_state.messages.append({"role": "user", "content": prompt})

    with st.chat_message("assistant"):
        output = ""
        stream = completion(
            model=st.session_state["model"],
            messages=st.session_state.messages,
            stream=True,
        )

        message_placeholder = st.empty()
        full_response = ""
        for chunk in stream:
            full_response += chunk.choices[0].delta.content or ""
            message_placeholder.markdown(full_response)
        msg = {"role": "assistant", "content": full_response}

        st.markdown("I used these references in making my response:")
        st.markdown(references)

    st.session_state.messages.append(msg)
