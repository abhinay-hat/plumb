# plumb — decision flow

Four gates stand between a question and an answer. Three of them exist to overrule the
language model. That is the whole design.

GitHub renders Mermaid natively, so both diagrams below display in the repo. Copy either
block into the README, a doc, or mermaid.live.

---

## Full flow

```mermaid
flowchart TD
    U(["Files uploaded<br/>CSV · XLSX · many at once"]) --> P["catalog.ingest<br/>profile every column"]
    P --> SC[["Schema card<br/>grain · history table · case-fold<br/>null coverage · foreign keys"]]
    Q(["Question in English"]) --> PL
    SC --> PL["planner.plan<br/>one model call"]
    DEF[/"Settled definitions<br/>pinned for the session"/] --> PL

    PL --> G1{"GATE 1<br/>Answerable from<br/>these columns?"}
    G1 -->|No| R1["REFUSE<br/>names what is missing"]
    G1 -->|Yes| G2{"GATE 2<br/>Every term defined<br/>by the data?"}

    G2 -->|No| CL["CLARIFY<br/>2–4 options naming<br/>real columns"]
    CL -->|User picks| DEF
    G2 -->|Yes| SQL["Model proposes SQL"]

    SQL --> G3{"GATE 3 — the guard<br/>Parses, resolves,<br/>and read-only?"}
    G3 -->|No · first failure| RP["Repair once<br/>guard error fed back"]
    RP --> G3
    G3 -->|No · failed twice| R2["REFUSE<br/>guard reason in plain words"]
    G3 -->|Yes| EX["Execute<br/>DuckDB · external access off"]

    EX --> NR["Model writes the sentence"]
    NR --> G4{"GATE 4<br/>Is every number<br/>actually in the rows?"}
    G4 -->|No| FB["Discard it<br/>deterministic fallback"]
    G4 -->|Yes| CH
    FB --> CH["Chart spec built in Python<br/>columns must exist · 2–50 rows"]

    CH --> AC(["ANSWER CARD<br/>sentence · table · chart · the SQL that ran"])
    AC --> AU[("Audit log<br/>one line per turn")]
    R1 --> AU
    R2 --> AU
    CL --> AU

    classDef gate fill:#e4e7f5,stroke:#3d4a8c,stroke-width:2px,color:#191c1f
    classDef refuse fill:#f6e6e4,stroke:#b8322a,stroke-width:2px,color:#191c1f
    classDef clarify fill:#f6eeda,stroke:#8a6414,stroke-width:2px,color:#191c1f
    classDef answer fill:#e2ede8,stroke:#2e6455,stroke-width:2px,color:#191c1f
    classDef shape fill:#f6e6e4,stroke:#b8322a,stroke-width:2px,color:#191c1f

    class G1,G2,G3,G4 gate
    class R1,R2,FB refuse
    class CL,DEF clarify
    class SQL,EX,AC answer
    class SC shape
```

---

## Compact — for the README

```mermaid
flowchart TD
    Q(["Question"]) --> G1{"Answerable from<br/>these columns?"}
    G1 -->|No| R["REFUSE"]
    G1 -->|Yes| G2{"Every term defined<br/>by the data?"}
    G2 -->|No| C["CLARIFY<br/>definition pinned for the session"]
    C --> Q
    G2 -->|Yes| S["Model proposes SQL"]
    S --> G3{"Guard: parses, resolves,<br/>read-only?"}
    G3 -->|No| R
    G3 -->|Yes| E["Execute on DuckDB"]
    E --> G4{"Every number in the<br/>sentence in the rows?"}
    G4 -->|No| F["Deterministic fallback"]
    G4 -->|Yes| A(["ANSWER<br/>sentence · table · chart · SQL"])
    F --> A

    classDef g fill:#e4e7f5,stroke:#3d4a8c,stroke-width:2px,color:#191c1f
    class G1,G2,G3,G4 g
```

---

## What each gate is for

**Gate 1 — answerable at all?** The first question isn't *what's the SQL*, it's *can these
columns answer this*. "Why is attrition going up" is causal; the sheet has statuses and
dates, not causes. It refuses and says what's missing rather than inventing a proxy.

**Gate 2 — is every term defined?** "Top performers" — top by what? "Headcount" — including
leavers? Those live in someone's head, not in the data. It asks, with options naming real
columns, and the choice is pinned for the session and shown on every answer that uses it.

**Gate 3 — the guard.** The model has written SQL and it still doesn't run. Parsed into a
syntax tree, every column resolved against the real schema, one statement, SELECT only, row
cap. Fail once and the error goes back for a repair; fail twice and you get an honest
refusal. A read-only DuckDB connection is not a security boundary — `read_csv_auto` still
reads any path and `COPY ... TO` still writes files — so external access is disabled too.

**Gate 4 — check the model's homework.** The query ran, so the numbers are real, but the
model still writes the sentence about them. Every number in it must appear in the returned
rows. If one doesn't, the sentence is discarded for a deterministic fallback. Years, dates
and figures from the question are context; an invented total fails.

The colours are hardcoded, so they won't follow dark mode. Delete the `classDef` and `class`
lines to let Mermaid use its own theme.
