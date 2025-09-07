# frontend/streamlit_app/pages/ai_rec.py
# author: mirada m
from __future__ import annotations
import os
import re
import requests
import streamlit as st

# For now, EVENTS are hardcoded.
EVENTS = [
    {
        "artist": "Drake",
        "genre": "hip hop",
        "date": "2025-09-10",
        "location": "Boston, MA",
        "price": 50,
    },
    {
        "artist": "Taylor Swift",
        "genre": "pop",
        "date": "2025-09-12",
        "location": "New York, NY",
        "price": 100,
    },
    {
        "artist": "Coldplay",
        "genre": "rock",
        "date": "2025-09-15",
        "location": "Boston, MA",
        "price": 75,
    },
]

# Readable context for the LLM
EVENTS_TEXT = "\n".join(
    f"- {e['artist']} | {e['genre']} | {e['date']} | {e['location']} | ${e['price']}"
    for e in EVENTS
)

# --- Configurable Ollama endpoint/model via environment variables -------------
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")

st.set_page_config(page_title="🎵 AI Event Recommender", layout="wide")
st.title("🎵 AI Event Recommender")
st.caption(
    "Type what you like & when you’re free. I’ll match the best concert from the list."
)

user_query = st.text_area(
    "Your preferences & availability",
    placeholder="e.g. I'm free Sept 12, prefer pop in New York, budget under 120",
)


def ollama_up() -> bool:
    """Quick health check for the Ollama daemon."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=2)
        return r.ok
    except Exception:
        return False


def ask_ollama(query: str) -> str:
    prompt = f"""
You are a concert-matching assistant.
The user said: "{query}"

Here are the available events:
{EVENTS_TEXT}

Pick the single best matching event.
Answer like:
"✅ The best match is Taylor Swift on 2025-09-12 in New York, NY ($100)."
"""
    url = f"{OLLAMA_BASE_URL}/api/generate"
    try:
        resp = requests.post(
            url,
            json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False},
            timeout=60,
        )
        # If the model isn't present, Ollama typically returns 404 with a JSON error
        if resp.status_code == 404:
            err = resp.json().get("error", "model not found")
            raise RuntimeError(
                f"Ollama says: {err}. Tip: pull it with "
                f"`docker exec -it ollama ollama pull {OLLAMA_MODEL}` "
                f"or set OLLAMA_MODEL to one you’ve pulled."
            )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "").strip()
    except requests.RequestException as e:
        raise RuntimeError(f"Ollama HTTP error at {url}: {e}") from e


def simple_match(query: str) -> str:
    """Heuristic fallback when Ollama isn't reachable."""
    q = query.lower()
    scored = []
    budget = None
    m = re.search(r"\bunder\s*\$?(\d+)|\$(\d+)|budget\s*(\d+)", q)
    if m:
        nums = [g for g in m.groups() if g]
        if nums:
            budget = int(nums[0])

    for e in EVENTS:
        s = 0
        if e["genre"].lower() in q:
            s += 2
        # compare city (before comma)
        city = e["location"].split(",")[0].lower()
        if city in q:
            s += 2
        if e["date"] in q:
            s += 1
        if budget is not None and e["price"] <= budget:
            s += 1
        scored.append((s, e))

    best = max(scored, key=lambda t: t[0])[1] if scored else EVENTS[0]
    return f"✅ The best match is {best['artist']} on {best['date']} in {best['location']} (${best['price']})."


if st.button("Find my concert"):
    if not user_query.strip():
        st.warning("Please type your availability or preferences.")
    else:
        with st.spinner("Finding the best match…"):
            try:
                if ollama_up():
                    st.success(ask_ollama(user_query))
                else:
                    st.info("Ollama not reachable; using quick local matching.")
                    st.success(simple_match(user_query))
            except Exception as ex:
                st.error(f"AI call failed: {ex}")
