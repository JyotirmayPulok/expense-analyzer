"""Remember the user's own Gemini key in THEIR browser (localStorage), never on the server.

On Streamlit Cloud one server serves every visitor, so a key saved in a server file would be shared with
everyone. localStorage belongs to the visitor's browser and this app's address only.

One small component is always on the page. It reports the saved key ("stored") and carries out a pending
save / clear command. Each command has a token, and the app keeps re-sending the command until the browser
answers with that token ("done"), so a rerun that interrupts the page update cannot lose it.
"""

from __future__ import annotations

import uuid

import streamlit as st

STORAGE_KEY = "expense_analyzer.gemini_key"

_JS = f"""
export default function(component) {{
    const {{ data, setStateValue }} = component;
    const K = "{STORAGE_KEY}";
    try {{
        if (data && data.token && window.__expenseKeyToken !== data.token) {{
            if (data.action === "save" && data.value) {{
                window.localStorage.setItem(K, data.value);
            }} else if (data.action === "clear") {{
                window.localStorage.removeItem(K);
            }}
            window.__expenseKeyToken = data.token;
        }}
    }} catch (e) {{ /* storage blocked (e.g. private window): the key just isn't remembered */ }}
    let value = "";
    try {{ value = window.localStorage.getItem(K) || ""; }} catch (e) {{ value = ""; }}
    // Report only changes: every report starts a rerun, and this function runs on every render.
    if (window.__expenseKeyReported !== value) {{
        window.__expenseKeyReported = value;
        setStateValue("stored", value);
    }}
    if (data && data.token && window.__expenseKeyDone !== data.token) {{
        window.__expenseKeyDone = data.token;
        setStateValue("done", data.token);
    }}
}}
"""

_store = st.components.v2.component("gemini_key_store", js=_JS)


def sync(pending: dict | None) -> tuple[str | None, str | None]:
    """Mount the store. Returns (saved key or None until the browser answers, token of the last finished command)."""
    result = _store(key="gemini_key_store", data=pending or {}, default={"stored": None, "done": None}, height=0,
                    on_stored_change=lambda: None, on_done_change=lambda: None)
    return result.stored, result.done


def command(action: str, value: str = "") -> dict:
    """A save / clear command for the next sync()."""
    cmd = {"action": action, "token": uuid.uuid4().hex}
    if value:
        cmd["value"] = value
    return cmd
