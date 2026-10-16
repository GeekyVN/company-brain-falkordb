import math

import streamlit as st
import streamlit.components.v1 as components

try:
    from pyvis.network import Network
    PYVIS_OK = True
    PYVIS_ERROR = ""
except Exception as e:  # keep the app usable even if the graph library fails to load
    PYVIS_OK = False
    PYVIS_ERROR = f"{type(e).__name__}: {e}"

from agent import ask, q
from updates import add_decision, current_decisions, list_people, reset_demo

st.set_page_config(page_title="Company Brain", page_icon="🧠", layout="wide")
st.title("🧠 Company Brain")
st.caption(
    "Ask about Northwind Labs. Every answer is built from a FalkorDB knowledge graph "
    "and shows which graph lookups and sources it used."
)

SAMPLES = {
    "Who owns what": [
        "Who owns Project Boreas?",
        "Who owns Sentinel Shield and which team is it in?",
        "Who owns Frostbite Pipeline?",
    ],
    "Decision history": [
        "What decisions were made about Project Boreas?",
        "What decisions were made about Aurora Analytics?",
        "What decisions were made about Polaris Design System?",
        "What decisions were made about Glacier Gateway?",
    ],
    "Why was it decided? (source tracing)": [
        "Why did we move away from Kubernetes operators in Project Boreas, and who approved it?",
        "Why did we switch the SIEM in Sentinel Shield?",
    ],
    "Who knows what": [
        "Who knows the most about Kubernetes?",
        "Who should I ask about disaster recovery?",
    ],
    "Multi-step questions": [
        "Who made the latest decision on Boreas, and does that person also own the project?",
    ],
    "Honest about what it doesn't know": [
        "Who owns the Phoenix project?",
        "What was our revenue last year?",
    ],
}

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


COLORS = {
    "Person": "#e879f9",
    "Project": "#3b82f6",
    "Decision": "#f87171",
    "Document": "#facc15",
    "Team": "#fb923c",
    "Ticket": "#4ade80",
    "Message": "#38bdf8",
}


@st.cache_data(show_spinner=False)
def path_graph_html(ids: tuple):
    """Draw the graph nodes the agent used, plus the relationships between them."""
    ids = list(ids)[:40]
    nodes = q(
        "MATCH (n) WHERE n.id IN $ids "
        "RETURN n.id, labels(n)[0], coalesce(n.name, n.title, n.summary)",
        {"ids": ids},
    )
    if not nodes:
        return None
    found = {n[0] for n in nodes}
    edges = q(
        "MATCH (a)-[r]->(b) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id, type(r), b.id",
        {"ids": ids},
    )
    net = Network(
        height="520px", width="100%", directed=True,
        bgcolor="#0e1117", font_color="white", cdn_resources="in_line",
    )
    # Fixed layout: positions are computed once here, so the picture never drifts.
    links = [(a, b) for a, _, b in edges if a in found and b in found]
    ordered = sorted(found)
    try:
        import networkx as nx

        G = nx.Graph()
        G.add_nodes_from(ordered)
        G.add_edges_from(links)
        pos = nx.spring_layout(G, seed=7, k=1.6 / max(len(ordered), 1) ** 0.5, iterations=200)
    except Exception:  # fallback: place the nodes evenly on a circle
        pos = {
            nid: (math.cos(2 * math.pi * i / len(ordered)), math.sin(2 * math.pi * i / len(ordered)))
            for i, nid in enumerate(ordered)
        }
    for nid, label, text in nodes:
        text = text or ""
        short = text if len(text) <= 28 else text[:25] + "..."
        x, y = pos[nid]
        net.add_node(nid, label=f"{nid}\n{short}", title=f"{label}: {text}",
                     shape="box", color=COLORS.get(label, "#9ca3af"),
                     font={"color": "#111827", "size": 16},
                     x=float(x) * 480, y=float(y) * 200, physics=False)
    for a, rel, b in edges:
        if a in found and b in found:
            net.add_edge(a, b, label=rel, color="#9ca3af")
    net.set_options(
        '{"edges":{"font":{"size":12,"color":"#e5e7eb","strokeWidth":3,"strokeColor":"#0e1117"},'
        '"smooth":{"type":"continuous"}},'
        '"nodes":{"margin":10},'
        '"physics":{"enabled":false}}'
    )
    html = net.generate_html()
    # After the first draw, zoom out just enough to show every node (never zoom in past 100%).
    hook = "network = new vis.Network(container, data, options);"
    fit = hook + ' network.once("afterDrawing", function () { network.fit({maxZoomLevel: 1.0, animation: false}); });'
    return html.replace(hook, fit, 1)


def show_details(trace):
    with st.expander("How this answer was built (graph lookups and sources)"):
        if not trace:
            st.info("No graph lookup was used. The agent answered that this is outside the company graph.")
            return
        st.markdown("**Graph lookups**")
        for step in trace:
            st.code(f"{step['tool']}({step['args']})  ->  {', '.join(step['sources']) or 'no results'}")
        sources = describe_sources(trace)
        if sources:
            st.markdown("**Sources in the graph**")
            st.dataframe(sources, use_container_width=True, hide_index=True)
        ids = tuple(sorted({i for step in trace for i in step["sources"]}))
        if ids and not PYVIS_OK:
            st.caption(f"Graph drawing is unavailable here ({PYVIS_ERROR}).")
        html = path_graph_html(ids) if (ids and PYVIS_OK) else None
        if html:
            st.markdown("**Graph path behind the answer**")
            st.caption(
                "Pink: person, blue: project, red: decision, yellow: document, "
                "orange: team, green: ticket, light blue: message. Hover a node for details."
            )
            components.html(html, height=540, scrolling=False)


# Sidebar with example questions
with st.sidebar:
    st.header("Try a question")
    st.caption("Click any question to see the answer, its sources, and the graph path.")
    for group, questions in SAMPLES.items():
        st.markdown(f"**{group}**")
        for s in questions:
            if st.button(s, use_container_width=True):
                st.session_state.pending = s
    if st.button("Clear chat", use_container_width=True):
        st.session_state.history = []
        st.rerun()

# Live knowledge update: add a decision that replaces a current one
with st.sidebar:
    st.divider()
    if "flash" in st.session_state:
        st.success(st.session_state.pop("flash"))
    with st.expander("Update the knowledge (live demo)"):
        st.caption(
            "Add a decision that replaces a current one, then ask about that project again. "
            "The answer changes, and the old decision is marked as superseded."
        )
        try:
            current = current_decisions()
            people = list_people()
        except Exception as e:
            current, people = [], []
            st.error(f"Could not read the graph: {e}")
        if current and people:
            summaries = dict(current)
            names = dict(people)
            with st.form("new_decision", clear_on_submit=True):
                old_id = st.selectbox(
                    "Decision to replace",
                    options=[c[0] for c in current],
                    format_func=lambda i: f"{i}: {summaries[i][:70]}",
                )
                person_id = st.selectbox(
                    "Made by", options=[p[0] for p in people], format_func=lambda i: names[i]
                )
                summary = st.text_input("New decision", max_chars=200)
                reason = st.text_area("Why was it made?", max_chars=600)
                submitted = st.form_submit_button("Add decision", use_container_width=True)
            if submitted:
                try:
                    did, docid = add_decision(old_id, summary, reason, person_id)
                    st.session_state.flash = (
                        f"Added {did} (source note {docid}). It now replaces {old_id}. "
                        "Ask about that project again to see the change."
                    )
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
        if st.button("Reset demo changes", use_container_width=True):
            removed = reset_demo()
            st.session_state.flash = f"Removed {removed} demo item(s). The original data is unchanged."
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
