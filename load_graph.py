import json

from falkordb import FalkorDB

GRAPH_NAME = "company_brain"

db = FalkorDB(host="localhost", port=6379)
g = db.select_graph(GRAPH_NAME)

# Start clean so the script can be rerun safely
try:
    g.delete()
except Exception:
    pass
g = db.select_graph(GRAPH_NAME)

skeleton = json.load(open("data/skeleton.json"))
docs = json.load(open("data/documents.json"))
rest = json.load(open("data/tickets_messages.json"))


def run(query, params=None):
    return g.query(query, params or {})


# ---------------- Indexes (faster lookups by id) ----------------
for label in ["Person", "Team", "Project", "Document", "Decision", "Ticket", "Message"]:
    try:
        run(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
    except Exception as e:
        print(f"index {label}: {str(e)[:60]}")

# ---------------- Teams, people, projects ----------------
for t in skeleton["teams"]:
    run("MERGE (n:Team {id:$id}) SET n.name=$name", t)

for p in skeleton["people"]:
    run("MERGE (n:Person {id:$id}) SET n.name=$name, n.role=$role", p)
    run(
        "MATCH (a:Person {id:$id}), (b:Team {id:$team_id}) MERGE (a)-[:MEMBER_OF]->(b)",
        p,
    )

for j in skeleton["projects"]:
    run("MERGE (n:Project {id:$id}) SET n.name=$name, n.description=$description", j)
    run(
        "MATCH (a:Person {id:$owner_id}), (b:Project {id:$id}) MERGE (a)-[:OWNS]->(b)",
        j,
    )
    run(
        "MATCH (a:Project {id:$id}), (b:Team {id:$team_id}) MERGE (a)-[:BELONGS_TO]->(b)",
        j,
    )

# ---------------- Documents ----------------
for d in docs["documents"]:
    run(
        "MERGE (n:Document {id:$id}) SET n.title=$title, n.date=$date, n.text=$text",
        d,
    )
    run(
        "MATCH (a:Person {id:$author_id}), (b:Document {id:$id}) MERGE (a)-[:AUTHORED]->(b)",
        d,
    )
    for pid in d.get("project_ids", []):
        run(
            "MATCH (a:Document {id:$id}), (b:Project {id:$pid}) MERGE (a)-[:MENTIONS]->(b)",
            {"id": d["id"], "pid": pid},
        )

# ---------------- Decisions ----------------
for x in docs["decisions"]:
    run("MERGE (n:Decision {id:$id}) SET n.summary=$summary, n.date=$date", x)
    run(
        "MATCH (a:Person {id:$made_by}), (b:Decision {id:$id}) MERGE (a)-[:MADE]->(b)",
        x,
    )
    run(
        "MATCH (a:Decision {id:$id}), (b:Document {id:$decided_in}) MERGE (a)-[:DECIDED_IN]->(b)",
        x,
    )
    for pid in x.get("affects", []):
        run(
            "MATCH (a:Decision {id:$id}), (b:Project {id:$pid}) MERGE (a)-[:AFFECTS]->(b)",
            {"id": x["id"], "pid": pid},
        )

# SUPERSEDES edges go from the newer decision to the older one.
# Done in a second pass so every Decision node exists first.
for x in docs["decisions"]:
    if x.get("supersedes"):
        run(
            "MATCH (new:Decision {id:$id}), (old:Decision {id:$old}) MERGE (new)-[:SUPERSEDES]->(old)",
            {"id": x["id"], "old": x["supersedes"]},
        )

# ---------------- Tickets ----------------
for t in rest["tickets"]:
    run(
        "MERGE (n:Ticket {id:$id}) SET n.title=$title, n.status=$status, n.date=$date, n.text=$text",
        t,
    )
    run(
        "MATCH (a:Person {id:$reporter_id}), (b:Ticket {id:$id}) MERGE (a)-[:REPORTED]->(b)",
        t,
    )
    run(
        "MATCH (a:Ticket {id:$id}), (b:Person {id:$assignee_id}) MERGE (a)-[:ASSIGNED_TO]->(b)",
        t,
    )
    run(
        "MATCH (a:Ticket {id:$id}), (b:Project {id:$project_id}) MERGE (a)-[:ABOUT]->(b)",
        t,
    )

# ---------------- Messages ----------------
for m in rest["messages"]:
    run("MERGE (n:Message {id:$id}) SET n.text=$text, n.date=$date", m)
    run(
        "MATCH (a:Person {id:$author_id}), (b:Message {id:$id}) MERGE (a)-[:SENT]->(b)",
        m,
    )
    run(
        "MATCH (a:Message {id:$id}), (b:Project {id:$project_id}) MERGE (a)-[:ABOUT]->(b)",
        m,
    )

# ---------------- Verification ----------------
print("\nNode counts:")
for row in run("MATCH (n) RETURN labels(n)[0] AS label, count(n) ORDER BY label").result_set:
    print(f"  {row[0]}: {row[1]}")

print("\nRelationship counts:")
for row in run("MATCH ()-[r]->() RETURN type(r) AS t, count(r) ORDER BY t").result_set:
    print(f"  {row[0]}: {row[1]}")

print("\nSample: decisions and what they replaced")
q = (
    "MATCH (p:Person)-[:MADE]->(new:Decision)-[:SUPERSEDES]->(old:Decision) "
    "RETURN p.name, new.summary, old.summary LIMIT 3"
)
for row in run(q).result_set:
    print(f"  {row[0]} decided: {row[1]}\n     (replacing: {row[2]})")

print(f"\nDone. Open http://localhost:3000 and select the graph '{GRAPH_NAME}'.")
