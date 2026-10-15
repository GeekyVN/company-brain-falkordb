import os
import json
import time

from dotenv import load_dotenv
from google import genai

load_dotenv()
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

# Models are tried in order. Edit this list to match what is available in AI Studio.
MODELS = ["gemini-3.5-flash", "gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]
os.makedirs("data", exist_ok=True)


def ask(prompt, retries=5):
    """Call Gemini and return parsed JSON. Retries and falls back to other models on errors."""
    for attempt in range(retries):
        for model in MODELS:
            try:
                r = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={"response_mime_type": "application/json"},
                )
                text = r.text.strip()
                # Remove markdown fences if the model added them anyway
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.lower().startswith("json"):
                        text = text[4:]
                return json.loads(text)
            except Exception as e:
                print(f"[{model}] failed: {str(e)[:100]}")
        wait = 10 * (attempt + 1)
        print(f"All models failed. Waiting {wait}s before retry {attempt + 2}/{retries}...")
        time.sleep(wait)
    raise RuntimeError("Gemini unavailable after retries. Wait a few minutes and rerun.")


def cached(path, make):
    """If the file exists, load it. Otherwise generate it and save it."""
    if os.path.exists(path):
        print(f"Using saved file: {path}")
        with open(path) as f:
            return json.load(f)
    print(f"Generating: {path}")
    data = make()
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    return data


# ---------------------------------------------------------------
# Stage 1: skeleton (teams, people, projects)
# ---------------------------------------------------------------
skeleton = cached(
    "data/skeleton.json",
    lambda: ask("""
Invent a fictional mid-size software company called "Northwind Labs".
Return JSON with exactly these keys:
- "teams": 4 items {"id":"T1","name":"..."}
- "people": 15 items {"id":"P1","name":"...","role":"...","team_id":"T1"}
- "projects": 6 items {"id":"J1","name":"...","description":"...","owner_id":"P1","team_id":"T1"}
Use realistic, diverse names. IDs must be unique and consistent
(owner_id must be a person id, team_id must be a team id).
"""),
)
ctx = json.dumps(skeleton)

# ---------------------------------------------------------------
# Stage 2: documents and decisions
# ---------------------------------------------------------------
docs = cached(
    "data/documents.json",
    lambda: ask(f"""
Company data: {ctx}

Write 20 internal documents (meeting notes, design docs, memos) for this company.
Return JSON in exactly this shape:
{{
  "documents": [
    {{"id":"D1","title":"...","author_id":"P1","date":"2026-03-14",
      "project_ids":["J1"],"text":"80-150 words"}}
  ],
  "decisions": [
    {{"id":"X1","summary":"...","made_by":"P1","decided_in":"D1",
      "affects":["J1"],"date":"2026-03-14","supersedes":null}}
  ]
}}

Requirements:
- 12 to 15 decisions, each tied to a document that explains the reasoning.
- At least 3 decisions must set "supersedes" to the id of an EARLIER decision
  (the new decision must have a later date than the one it replaces).
- Include one clear story: a vendor or technology switch, with who approved it and why.
- Only use person, project, and document IDs that exist in the company data or in your documents.
- Dates must be between 2026-01-01 and 2026-09-30.
"""),
)

# ---------------------------------------------------------------
# Stage 3: tickets and chat messages
# ---------------------------------------------------------------
rest = cached(
    "data/tickets_messages.json",
    lambda: ask(f"""
Company data: {ctx}
Decisions (for reference): {json.dumps(docs["decisions"])}

Return JSON in exactly this shape:
{{
  "tickets": [
    {{"id":"K1","title":"...","reporter_id":"P1","assignee_id":"P2",
      "project_id":"J1","status":"open","date":"2026-05-02","text":"30-60 words"}}
  ],
  "messages": [
    {{"id":"M1","author_id":"P1","project_id":"J1","date":"2026-05-02",
      "text":"1-3 sentences of casual chat"}}
  ]
}}

Requirements:
- 20 tickets and 30 messages.
- status is either "open" or "closed".
- Several tickets and messages should refer to the decisions above by topic (not by id).
- Only use person and project IDs that exist in the company data.
"""),
)

# ---------------------------------------------------------------
# Validation
# ---------------------------------------------------------------
pids = {p["id"] for p in skeleton["people"]}
jids = {j["id"] for j in skeleton["projects"]}
tids = {t["id"] for t in skeleton["teams"]}
dids = {d["id"] for d in docs["documents"]}
xids = {x["id"] for x in docs["decisions"]}

problems = []

for p in skeleton["people"]:
    if p["team_id"] not in tids:
        problems.append(f"person {p['id']}: bad team_id")
for j in skeleton["projects"]:
    if j["owner_id"] not in pids:
        problems.append(f"project {j['id']}: bad owner_id")
    if j["team_id"] not in tids:
        problems.append(f"project {j['id']}: bad team_id")
for d in docs["documents"]:
    if d["author_id"] not in pids:
        problems.append(f"document {d['id']}: bad author_id")
    for pj in d.get("project_ids", []):
        if pj not in jids:
            problems.append(f"document {d['id']}: bad project id {pj}")
for x in docs["decisions"]:
    if x["made_by"] not in pids:
        problems.append(f"decision {x['id']}: bad made_by")
    if x["decided_in"] not in dids:
        problems.append(f"decision {x['id']}: bad decided_in")
    for pj in x.get("affects", []):
        if pj not in jids:
            problems.append(f"decision {x['id']}: bad affected project {pj}")
    if x.get("supersedes") and x["supersedes"] not in xids:
        problems.append(f"decision {x['id']}: bad supersedes {x['supersedes']}")
for t in rest["tickets"]:
    if t["reporter_id"] not in pids or t["assignee_id"] not in pids:
        problems.append(f"ticket {t['id']}: bad person id")
    if t["project_id"] not in jids:
        problems.append(f"ticket {t['id']}: bad project_id")
for m in rest["messages"]:
    if m["author_id"] not in pids:
        problems.append(f"message {m['id']}: bad author_id")
    if m["project_id"] not in jids:
        problems.append(f"message {m['id']}: bad project_id")

print()
print(
    f"teams {len(tids)} | people {len(pids)} | projects {len(jids)} | "
    f"documents {len(dids)} | decisions {len(xids)} | "
    f"tickets {len(rest['tickets'])} | messages {len(rest['messages'])}"
)
superseding = sum(1 for x in docs["decisions"] if x.get("supersedes"))
print(f"decisions that supersede an earlier one: {superseding}")
print(f"broken references: {len(problems)}")
for p in problems[:20]:
    print("  -", p)
if problems:
    print("\nTo regenerate a stage, delete its file in data/ and run again.")
