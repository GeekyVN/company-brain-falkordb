# 🧠 Company Brain

**An agent that understands how a company works, built on a FalkorDB knowledge graph.**
Ask who owns what, who knows what, and why a decision was made. Every answer cites its sources and shows the exact graph path behind it.

Built for **Graph Hacks: Context for AI Agents** (WeMakeDevs × FalkorDB) · **Track 03: Company Brain**

| | |
|---|---|
| **Live demo** | https://falkordb-company-brain.streamlit.app/ |
| **Repository** | https://github.com/GeekyVN/company-brain-falkordb |
| **Demo video** | https://youtu.be/RTSbBN0zS7A (backup copy: https://drive.google.com/file/d/1P_Pwk0Gh5DeUyVOYliVvV_sbEL6aGPLx/view?usp=sharing) |
| **Blog post** | https://medium.com/@vishweshneelesh99/company-brain-how-i-taught-an-ai-agent-to-understand-a-company-using-a-knowledge-graph-2ab50f87b8c0 |

> The live demo uses a FalkorDB Cloud free-tier instance and a free Gemini key. If the demo is slow, rate-limited, or the database has been stopped for inactivity, follow the local setup below. It takes about five minutes.

---

## What it does

Company knowledge is scattered across documents, tickets, and chat messages. Company Brain connects people, teams, projects, documents, tickets, messages, and decisions in **one graph**, so an agent can answer questions by following relationships instead of guessing from text.

- **Who owns what.** "Who owns Project Boreas, and which team is it in?"
- **Who knows what.** "Who knows the most about Kubernetes?"
- **Decision history.** "What decisions were made about Project Boreas, and which are still current?"
- **Tracing decisions to their source.** "Why did we move away from Kubernetes operators, and who approved it?" The agent follows the decision to the document that explains it and reads the reasoning.
- **Knowledge that stays current.** Add a decision that replaces an earlier one in the live demo, ask again, and the answer changes. The old decision is marked as superseded.
- **Answers with clear sources.** Each answer cites graph IDs like `[X7]` and `[D7]`, lists the graph lookups used, shows the source nodes, and draws the path in the graph.
- **Honest about what it doesn't know.** If something isn't in the graph, it says so instead of inventing an answer.

## How it maps to the Track 03 key focus

| Track 03 key focus | How Company Brain does it |
|---|---|
| Knowledge from docs, tickets, and chats in one graph | Documents, Tickets, and Messages are nodes linked to People, Projects, and Decisions |
| Who owns what, and who knows what | `OWNS` and `BELONGS_TO` edges; `who_knows` traverses `AUTHORED`, `REPORTED`, and `SENT` edges |
| Tracing decisions back to their source | `Decision -[:DECIDED_IN]-> Document`, plus a `trace_source` tool that reads the document |
| Keeping knowledge current as things change | `Decision -[:SUPERSEDES]-> Decision` edges, and a live form that adds new superseding decisions |
| Answers with clear sources | Cited IDs, a sources table, and a graph path for every answer |

## Why a graph

The questions this system answers are about **relationships**: a person made a decision, which affected a project, which replaced an earlier decision, which came from a document. In a relational database these are chains of joins. In FalkorDB they are short traversals, and the same traversal is what the interface draws as the "path behind the answer". If FalkorDB were removed, there would be nothing left to answer from.

## Architecture

```
Question ──▶ Gemini (function calling) ──▶ picks a tool
                                              │
                          who_owns · who_knows · find_decisions
                          decision_history · trace_source
                                              │  fixed, parameterised Cypher
                                              ▼
                                      FalkorDB knowledge graph
                                              │  rows + node IDs
                                              ▼
              Gemini writes the answer, citing IDs ──▶ Streamlit UI
                                              │
                        graph lookups used · sources table · graph path
```

The LLM never writes Cypher. It chooses among five tools, and each tool runs a fixed, parameterised query. That keeps answers predictable and makes every claim traceable to graph nodes.

## Graph data model

**Nodes**

| Label | Key properties |
|---|---|
| `Team` | `id`, `name` |
| `Person` | `id`, `name`, `role` |
| `Project` | `id`, `name`, `description` |
| `Document` | `id`, `title`, `date`, `text` |
| `Decision` | `id`, `summary`, `date` |
| `Ticket` | `id`, `title`, `status`, `date`, `text` |
| `Message` | `id`, `text`, `date` |

**Relationships**

| Relationship | Meaning |
|---|---|
| `(Person)-[:MEMBER_OF]->(Team)` | Team membership |
| `(Person)-[:OWNS]->(Project)` | Project owner |
| `(Project)-[:BELONGS_TO]->(Team)` | Team responsible for the project |
| `(Person)-[:AUTHORED]->(Document)` | Who wrote a document |
| `(Document)-[:MENTIONS]->(Project)` | Projects a document covers |
| `(Person)-[:MADE]->(Decision)` | Who made a decision |
| `(Decision)-[:DECIDED_IN]->(Document)` | The document that records the reasoning |
| `(Decision)-[:AFFECTS]->(Project)` | Projects the decision applies to |
| `(Decision)-[:SUPERSEDES]->(Decision)` | The newer decision replaces the older one |
| `(Person)-[:REPORTED]->(Ticket)` / `(Ticket)-[:ASSIGNED_TO]->(Person)` | Ticket reporter and assignee |
| `(Ticket)-[:ABOUT]->(Project)` | Project a ticket concerns |
| `(Person)-[:SENT]->(Message)` / `(Message)-[:ABOUT]->(Project)` | Chat messages and their project |

The bundled dataset loads **109 nodes and 236 relationships**.

## Key Cypher queries

**Who owns a project** (`who_owns`)
```cypher
MATCH (p:Person)-[:OWNS]->(j:Project)
WHERE toLower(j.name) CONTAINS toLower($name)
OPTIONAL MATCH (j)-[:BELONGS_TO]->(t:Team)
RETURN j.id, j.name, p.id, p.name, p.role, t.name
```

**Decision history, showing what replaced what** (`decision_history`)
```cypher
MATCH (d:Decision)-[:AFFECTS]->(j:Project)
WHERE toLower(j.name) CONTAINS toLower($name)
MATCH (m:Person)-[:MADE]->(d)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
RETURN d.id, d.date, d.summary, m.name, old.id, newer.id, j.id
ORDER BY d.date
```

**Find decisions by topic** (`find_decisions`)
```cypher
MATCH (m:Person)-[:MADE]->(d:Decision)-[:DECIDED_IN]->(doc:Document)
WHERE toLower(d.summary) CONTAINS toLower($k) OR toLower(doc.text) CONTAINS toLower($k)
OPTIONAL MATCH (d)-[:SUPERSEDES]->(old:Decision)
OPTIONAL MATCH (newer:Decision)-[:SUPERSEDES]->(d)
RETURN d.id, d.date, d.summary, m.name, doc.id, doc.title, old.id, newer.id
ORDER BY d.date
```

**Trace a decision to its source document** (`trace_source`)
```cypher
MATCH (m:Person)-[:MADE]->(d:Decision {id:$id})-[:DECIDED_IN]->(doc:Document)
OPTIONAL MATCH (a:Person)-[:AUTHORED]->(doc)
RETURN d.id, d.summary, d.date, m.name, doc.id, doc.title, doc.date, doc.text, a.name
```

**Who knows a topic** (`who_knows`): people connected to matching documents, tickets, or messages, directly or through a project
```cypher
MATCH (p:Person)-[r:AUTHORED|SENT|REPORTED]->(x)-[:ABOUT|MENTIONS]->(j:Project)
WHERE toLower(j.name) CONTAINS toLower($t)
RETURN p.id, p.name, type(r), x.id
```

**Live update: add a decision that supersedes another** (`updates.py`)
```cypher
MATCH (p:Person {id:$pid}), (old:Decision {id:$old})
CREATE (doc:Document {id:$docid, title:$title, date:$date, text:$reason, demo:true})
CREATE (d:Decision {id:$did, summary:$summary, date:$date, demo:true})
CREATE (p)-[:AUTHORED]->(doc)
CREATE (p)-[:MADE]->(d)
CREATE (d)-[:DECIDED_IN]->(doc)
CREATE (d)-[:SUPERSEDES]->(old)
```
Everything added through the form is flagged `demo:true`, so **Reset demo changes** removes it without touching the original data.

## Try it

Use the grouped sample questions in the sidebar of the live app. Good ones to start with:

1. **Who owns Project Boreas?**
2. **What decisions were made about Project Boreas?** Shows X1 superseded by X7, with the path drawn.
3. **Why did we move away from Kubernetes operators in Project Boreas, and who approved it?** Chains `decision_history` and `trace_source` to read the source document.
4. **Who owns the Phoenix project?** The project doesn't exist, and the agent says so.

**Live knowledge update**
1. Open "Update the knowledge (live demo)" at the bottom of the sidebar.
2. Replace a current decision, choose who made the new one, and write the decision and its reason.
3. Ask about that project again. The new decision is current, the old one is superseded, and the graph path shows the new chain.
4. Click **Reset demo changes** to restore the original data.

All visitors share one graph, so please reset after trying the form.

## Run it locally

**Requirements:** Python 3.11+, Docker, and a free [Google AI Studio](https://aistudio.google.com) API key.

```bash
git clone https://github.com/GeekyVN/company-brain-falkordb.git
cd company-brain-falkordb
pip install -r requirements.txt

# 1. Start FalkorDB (browser UI at http://localhost:3000)
docker run -d --name falkordb -p 6379:6379 -p 3000:3000 \
  -v falkordb_data:/data falkordb/falkordb:latest

# 2. Set your Gemini key
export GEMINI_API_KEY="your-key"

# 3. Load the bundled dataset into the graph
python load_graph.py

# 4. Run the app (http://localhost:8501)
streamlit run app.py
```

To use a hosted FalkorDB instead of local Docker, also set `FALKORDB_HOST`, `FALKORDB_PORT`, `FALKORDB_USERNAME`, and `FALKORDB_PASSWORD`. When they're unset, the app connects to `localhost:6379`.

**Regenerate the dataset (optional).** The `data/` folder is included, but `python generate_data.py` produces a new synthetic company with Gemini. Each stage is saved separately, so a failed run resumes where it stopped. Run `load_graph.py` afterwards to rebuild the graph.

## Project structure

```
app.py            Streamlit interface: chat, sources, graph path, live update form
agent.py          Five graph tools + Gemini function calling + source tracing
updates.py        Live knowledge update and reset (adds superseding decisions)
load_graph.py     Builds the FalkorDB graph from the JSON files
generate_data.py  Generates the synthetic company data with Gemini
data/             skeleton.json, documents.json, tickets_messages.json
requirements.txt  Python dependencies
```

## Data

The dataset is **fully synthetic**: a fictional company, "Northwind Labs", with 4 teams, 15 people, 6 projects, 20 documents, 14 decisions, 20 tickets, and 30 chat messages, generated with Gemini and checked by a script for broken references. It contains no real or private data.

## Tech stack

- **FalkorDB**: the graph database (Cypher), via the official Python client
- **Google Gemini** (`google-genai` SDK): function calling and answer writing, with automatic fallback across several models
- **Streamlit**: the interface, deployed on Streamlit Community Cloud
- **pyvis / networkx**: the graph path visualisation with a fixed layout
- **FalkorDB Cloud** (free tier) for the hosted demo database

## Limitations

- `who_knows` ranks people by how many matching documents, tickets, and messages they wrote. It is keyword-based and does not yet use graph algorithms such as PageRank.
- The dataset is small and synthetic, built to demonstrate the approach.
- The live demo uses free tiers. The Gemini quota is shared by all visitors, and the free FalkorDB instance stops after a day of inactivity and is deleted after a week without use.
- The live update form writes to a shared graph with no authentication. It is flagged and resettable, and meant for demonstration only.
- The LLM can still misread a result. That is why every answer shows the lookups, the cited IDs, and the graph path so it can be checked.
- The agent answers questions and traces decisions. It does not take actions in external systems yet, and it has no memory between sessions.

## What I'd build next

- Rank experts with a graph algorithm such as PageRank or centrality, instead of keyword counts in `who_knows`.
- Add vector search, so questions can start from meaning as well as keywords.
- Store "approved by" relationships in the graph. Right now that detail lives in the document text.
- Keep a separate memory graph for each user, so the agent can remember earlier sessions.
- Let the agent propose actions (for example, flag an owner or draft an escalation) that a person approves.

## AI assistance disclosure

In line with the hackathon rules, AI assistants were used in this project:

- **Claude (Anthropic)** was used as a coding assistant to help design the graph model and to write and debug the code.
- **Google Gemini** is used at runtime to choose tools and write answers, and was used to generate the synthetic dataset.

I tested the system against the source data, verified the answers and cited IDs, and am responsible for the submission.

**What I did myself:** chose the track and the scope; set up FalkorDB locally and on FalkorDB Cloud, the repository, and the deployment; ran and tested every stage; checked answers against the source data and fixed weak links in the generated dataset; and decided the product features, including the sample questions, the stable graph view, and the live update.

## Author

**Vishwesh** · GitHub: [@GeekyVN](https://github.com/GeekyVN)
