import streamlit as st

from agent import ask, q

st.set_page_config(page_title="Company Brain", page_icon="🧠", layout="wide")
st.title("🧠 Company Brain")
st.caption(
    "Ask about Northwind Labs. Every answer is built from a FalkorDB knowledge graph "
    "and shows which graph lookups and sources it used."
)

SAMPLES = [
    "Who owns Project Boreas?",
    "What decisions were made about Project Boreas?",
    "Why did we move away from Kubernetes operators in Project Boreas, and who approved it?",
    "Who knows the most about Kubernetes?",
    "What decisions were made about Aurora Analytics?",
    "Who owns the Phoenix project?",
]

if "history" not in st.session_state:
    st.session_state.history = []


def describe_sources(trace):
    """Look up a readable name for every graph ID the agent touched."""
    ids = sorted({i for step in trace for i in step["sources"]})
    if not ids:
        return []
    rows = q(
        "MATCH (n) WHERE n.id IN $ids "
        "RETURN n.id, labels(n)[0], coalesce(n.name, n.title, n.summary)",
        {"ids": ids},
    )
    return [{"ID": r[0], "Type": r[1], "Name / title": r[2]} for r in sorted(rows, key=lambda r: r[0])]


def show_details(trace):
    with st.expander("How this answer was built (graph lookups and sources)"):
        if not trace:
            st.warning("No graph lookup was used for this answer.")
            return
        st.markdown("**Graph lookups**")
        for step in trace:
            st.code(f"{step['tool']}({step['args']})  ->  {', '.join(step['sources']) or 'no results'}")
        sources = describe_sources(trace)
        if sources:
            st.markdown("**Sources in the graph**")
            st.dataframe(sources, use_container_width=True, hide_index=True)


# Sidebar with example questions
with st.sidebar:
    st.header("Try a question")
    for s in SAMPLES:
        if st.button(s, use_container_width=True):
            st.session_state.pending = s
    if st.button("Clear chat", use_container_width=True):
        st.session_state.history = []
        st.rerun()

# Show earlier turns
for turn in st.session_state.history:
    with st.chat_message("user"):
        st.write(turn["q"])
    with st.chat_message("assistant"):
        st.markdown(turn["a"])
        show_details(turn["trace"])

# New question (typed, or clicked in the sidebar)
question = st.chat_input("Ask about people, projects, decisions...")
if not question:
    question = st.session_state.pop("pending", None)

if question:
    with st.chat_message("user"):
        st.write(question)
    with st.chat_message("assistant"):
        with st.spinner("Searching the graph..."):
            try:
                answer, trace = ask(question)
            except Exception as e:
                answer, trace = f"Sorry, something went wrong: {e}", []
        st.markdown(answer)
        show_details(trace)
    st.session_state.history.append({"q": question, "a": answer, "trace": trace})
