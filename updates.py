"""Live knowledge updates for the Company Brain graph.

Everything added here is flagged demo=true, so reset_demo() can remove it
without touching the original dataset.
"""
import datetime

from agent import q

MAX_SUMMARY = 200
MAX_REASON = 600


def current_decisions():
    """Decisions that have not been replaced by a later one: [(id, summary), ...]."""
    rows = q(
        """
        MATCH (d:Decision)
        OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
        WITH d, newer
        WHERE newer IS NULL
        RETURN d.id, d.summary, d.date
        ORDER BY d.date
        """
    )
    return [(r[0], r[1]) for r in rows]


def list_people():
    """All people: [(id, 'Name (role)'), ...]."""
    rows = q("MATCH (p:Person) RETURN p.id, p.name, p.role ORDER BY p.name")
    return [(r[0], f"{r[1]} ({r[2]})") for r in rows]


def _next_id(label, prefix):
    rows = q(f"MATCH (n:{label}) RETURN n.id")
    nums = []
    for (node_id,) in rows:
        tail = node_id[len(prefix):] if node_id.startswith(prefix) else ""
        if tail.isdigit():
            nums.append(int(tail))
    return f"{prefix}{max(nums, default=0) + 1}"


def add_decision(old_id, summary, reason, person_id):
    """Add a new decision (plus a note explaining it) that supersedes old_id.

    Returns (new_decision_id, new_document_id).
    """
    summary = (summary or "").strip()
    reason = (reason or "").strip()
    if not summary or not reason:
        raise ValueError("Please fill in both the decision and the reason.")
    if len(summary) > MAX_SUMMARY or len(reason) > MAX_REASON:
        raise ValueError(
            f"Keep the decision under {MAX_SUMMARY} characters and the reason under {MAX_REASON}."
        )

    did = _next_id("Decision", "X")
    docid = _next_id("Document", "D")
    params = {
        "old": old_id,
        "pid": person_id,
        "did": did,
        "docid": docid,
        "summary": summary,
        "reason": reason,
        "title": f"Decision note: {summary[:60]}",
        "date": datetime.date.today().isoformat(),
    }

    # Parameterised queries: user text is stored as data, never run as Cypher.
    created = q(
        """
        MATCH (p:Person {id:$pid}), (old:Decision {id:$old})
        CREATE (doc:Document {id:$docid, title:$title, date:$date, text:$reason, demo:true})
        CREATE (d:Decision {id:$did, summary:$summary, date:$date, demo:true})
        CREATE (p)-[:AUTHORED]->(doc)
        CREATE (p)-[:MADE]->(d)
        CREATE (d)-[:DECIDED_IN]->(doc)
        CREATE (d)-[:SUPERSEDES]->(old)
        RETURN d.id
        """,
        params,
    )
    if not created:
        raise ValueError("Could not find that person or decision. Refresh the page and try again.")

    # The new decision affects the same projects as the one it replaces.
    q(
        """
        MATCH (old:Decision {id:$old})-[:AFFECTS]->(j:Project),
              (d:Decision {id:$did}), (doc:Document {id:$docid})
        MERGE (d)-[:AFFECTS]->(j)
        MERGE (doc)-[:MENTIONS]->(j)
        """,
        params,
    )
    return did, docid


def reset_demo():
    """Remove everything added through add_decision. Returns how many nodes were removed."""
    count = q("MATCH (n) WHERE n.demo = true RETURN count(n)")[0][0]
    if count:
        q("MATCH (n) WHERE n.demo = true DELETE n")
    return count
