import os
import time

from dotenv import load_dotenv
from falkordb import FalkorDB
from google import genai
from google.genai import types

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Tried in order. Edit to match the models available to your key.
MODELS = ["gemini-3.5-flash-lite", "gemini-3.5-flash", "gemini-3.1-flash-lite", "gemini-3.6-flash"]

db = FalkorDB(
    host=os.getenv("FALKORDB_HOST", "localhost"),
    port=int(os.getenv("FALKORDB_PORT", "6379")),
    username=os.getenv("FALKORDB_USERNAME") or None,
    password=os.getenv("FALKORDB_PASSWORD") or None,
)
g = db.select_graph("company_brain")

# Every tool call is recorded here so the UI can show which graph parts were used.
TRACE = []


def q(query, params=None):
    return g.query(query, params or {}).result_set


def log(tool, args, sources):
    TRACE.append({"tool": tool, "args": args, "sources": sorted(set(s for s in sources if s))})


# ======================================================================
# TOOLS (each one runs fixed Cypher and returns plain data + source IDs)
# ======================================================================
def who_owns(project: str) -> dict:
    """Find who owns a project and which team it belongs to.

    Args:
        project: Project name or a distinctive part of it, e.g. "Atlas".
    """
    if project.strip().lower() in {"", "project", "projects", "the", "a"}:
        log("who_owns", {"project": project}, [])
        return {"results": []}
    rows = q(
        """
        MATCH (p:Person)-[:OWNS]->(j:Project)
        WHERE toLower(j.name) CONTAINS toLower($name)
        OPTIONAL MATCH (j)-[:BELONGS_TO]->(t:Team)
        RETURN j.id, j.name, p.id, p.name, p.role, t.name
        """,
        {"name": project},
    )
    results = [
        {"project_id": r[0], "project": r[1], "owner_id": r[2], "owner": r[3], "role": r[4], "team": r[5]}
        for r in rows
    ]
    log("who_owns", {"project": project}, [x for r in rows for x in (r[0], r[2])])
    return {"results": results}


def who_knows(topic: str) -> dict:
    """Find the people who know most about a topic or project, based on the documents they
    wrote, the tickets they reported and the chat messages they sent about it.

    Args:
        topic: A single keyword or project name, e.g. "billing" or "Atlas".
    """
    people = {}

    def add(pid, name, kind, item_id):
        entry = people.setdefault(pid, {"person_id": pid, "person": name, "items": {}})
        entry["items"].setdefault(kind, []).append(item_id)

    direct = q(
        """
        MATCH (p:Person)-[r:AUTHORED|SENT|REPORTED]->(x)
        WHERE toLower(x.text) CONTAINS toLower($t) OR toLower(coalesce(x.title, '')) CONTAINS toLower($t)
        RETURN p.id, p.name, type(r), x.id
        """,
        {"t": topic},
    )
    via_project = q(
        """
        MATCH (p:Person)-[r:AUTHORED|SENT|REPORTED]->(x)-[:ABOUT|MENTIONS]->(j:Project)
        WHERE toLower(j.name) CONTAINS toLower($t)
        RETURN p.id, p.name, type(r), x.id
        """,
        {"t": topic},
    )
    seen = set()
    for pid, name, kind, item_id in direct + via_project:
        if (pid, item_id) in seen:
            continue
        seen.add((pid, item_id))
        add(pid, name, kind, item_id)

    ranked = sorted(people.values(), key=lambda p: -sum(len(v) for v in p["items"].values()))[:5]
    for p in ranked:
        p["total_items"] = sum(len(v) for v in p["items"].values())
    log("who_knows", {"topic": topic}, [x for p in ranked for v in p["items"].values() for x in v] + [p["person_id"] for p in ranked])
    return {"top_people": ranked}


def find_decisions(keyword: str) -> dict:
    """Search decisions by a keyword found in the decision summary or in the document that
    explains it. Shows who made each decision, when, and whether it was later replaced.

    Args:
        keyword: A single keyword such as "vendor", "database" or "migration".
    """
    rows = q(
        """
        MATCH (m:Person)-[:MADE]->(d:Decision)-[:DECIDED_IN]->(doc:Document)
        WHERE toLower(d.summary) CONTAINS toLower($k) OR toLower(doc.text) CONTAINS toLower($k)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
        OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
        RETURN d.id, d.date, d.summary, m.name, doc.id, doc.title, old.id, newer.id
        ORDER BY d.date
        """,
        {"k": keyword},
    )
    results = [
        {
            "decision_id": r[0], "date": r[1], "summary": r[2], "made_by": r[3],
            "document_id": r[4], "document_title": r[5],
            "replaces": r[6], "replaced_by": r[7],
            "status": f"superseded by {r[7]}" if r[7] else "current",
        }
        for r in rows
    ]
    log("find_decisions", {"keyword": keyword}, [x for r in rows for x in (r[0], r[4], r[6], r[7])])
    return {"decisions": results}


def decision_history(project: str) -> dict:
    """List every decision that affected a project in date order, with who made it and
    whether it is still current or was replaced by a later decision.

    Args:
        project: Project name or part of it.
    """
    if project.strip().lower() in {"", "project", "projects", "the", "a"}:
        log("decision_history", {"project": project}, [])
        return {"history": []}
    rows = q(
        """
        MATCH (d:Decision)-[:AFFECTS]->(j:Project)
        WHERE toLower(j.name) CONTAINS toLower($name)
        MATCH (m:Person)-[:MADE]->(d)
        OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
        OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
        RETURN d.id, d.date, d.summary, m.name, old.id, newer.id, j.id
        ORDER BY d.date
        """,
        {"name": project},
    )
    results = [
        {
            "decision_id": r[0], "date": r[1], "summary": r[2], "made_by": r[3],
            "replaces": r[4], "replaced_by": r[5],
            "status": f"superseded by {r[5]}" if r[5] else "current",
        }
        for r in rows
    ]
    log("decision_history", {"project": project}, [x for r in rows for x in (r[0], r[4], r[5], r[6])])
    return {"history": results}


def trace_source(decision_id: str) -> dict:
    """Trace a decision back to its source document and show the reasoning in that document.

    Args:
        decision_id: A decision id such as "X3" (taken from other tool results).
    """
    rows = q(
        """
        MATCH (m:Person)-[:MADE]->(d:Decision {id:$id})-[:DECIDED_IN]->(doc:Document)
        OPTIONAL MATCH (a:Person)-[:AUTHORED]->(doc)
        RETURN d.id, d.summary, d.date, m.name, doc.id, doc.title, doc.date, doc.text, a.name
        """,
        {"id": decision_id},
    )
    results = [
        {
            "decision_id": r[0], "decision": r[1], "decision_date": r[2], "made_by": r[3],
            "document_id": r[4], "document_title": r[5], "document_date": r[6],
            "document_text": r[7], "document_author": r[8],
        }
        for r in rows
    ]
    log("trace_source", {"decision_id": decision_id}, [x for r in rows for x in (r[0], r[4])])
    return {"sources": results}


TOOLS = [who_owns, who_knows, find_decisions, decision_history, trace_source]


# ======================================================================
# AGENT
# ======================================================================
def build_system_prompt():
    projects = ", ".join(r[0] for r in q("MATCH (j:Project) RETURN j.name"))
    return f"""You are Company Brain, an assistant that answers questions about a company using a knowledge graph.

Known projects: {projects}

Rules:
- Always use the tools to look things up. Never answer from your own knowledge.
- Tool arguments should be short keywords or project names, not whole sentences.
- If a lookup returns no results, stop and say you could not find it. Do not retry with a shorter or more generic keyword, and never search for unrelated projects or people.
- For "why" questions about a decision, call trace_source on the decision id to read the reasoning.
- Mention whether a decision is current or was superseded.
- Always cite the IDs you used in square brackets, including for ownership answers, for example [J1] and [P2], [X3] or [D7].
- If the tools do not contain the answer, say so plainly. Do not invent facts.
- Keep answers short and clear."""


def ask(question: str):
    """Returns (answer_text, trace). trace lists every tool call with the IDs it touched."""
    system = build_system_prompt()
    for attempt in range(4):
        for model in MODELS:
            TRACE.clear()
            try:
                r = client.models.generate_content(
                    model=model,
                    contents=question,
                    config=types.GenerateContentConfig(
                        system_instruction=system, tools=TOOLS, temperature=0.2
                    ),
                )
                return r.text, list(TRACE)
            except Exception as e:
                print(f"[{model}] failed: {str(e)[:100]}")
        wait = 10 * (attempt + 1)
        print(f"Waiting {wait}s before retrying...")
        time.sleep(wait)
    raise RuntimeError("Gemini unavailable after retries.")


if __name__ == "__main__":
    print("Company Brain ready. Type a question, or 'quit' to exit.")
    while True:
        question = input("\nYou: ").strip()
        if question.lower() in ("quit", "exit", ""):
            break
        answer, trace = ask(question)
        print(f"\nAnswer:\n{answer}")
        print("\nGraph lookups used:")
        for step in trace:
            print(f"  - {step['tool']}({step['args']}) -> {', '.join(step['sources'])}")
