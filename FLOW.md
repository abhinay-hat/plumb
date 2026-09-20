# plumb — how a question becomes an answer

One planner call decides the route. Four gates stand between that decision and
anything a user sees, and three of them exist to overrule the model.

Read it top to bottom.

```mermaid
flowchart TD
    F(["Files uploaded<br/>CSV · XLSX · several at once"]) --> ING["catalog.ingest<br/>profile every column"]
    ING --> SC[["SCHEMA CARD<br/>grain · history table · case-folding<br/>null coverage · foreign keys"]]

    Q(["Question in English"]) --> PL
    SC --> PL
    DEF[/"Settled definitions<br/>pinned for this session"/] --> PL

    PL["planner.plan — ONE model call<br/><i>router picks a model, fails over when one is busy</i>"]

    PL --> D0{"About the data<br/>at all?"}
    D0 -->|No| CHAT["CHAT<br/>short reply, real column names<br/>no SQL, nothing invented"]

    D0 -->|Yes| G1{"GATE 1<br/>Answerable from<br/>these columns?"}
    G1 -->|No| REF["REFUSE<br/>names what is missing"]

    G1 -->|Yes| G2{"GATE 2<br/>Every term defined<br/>by the data?"}
    G2 -->|No| CLR["CLARIFY<br/>2–4 readings, each naming<br/>real columns"]
    CLR -->|User picks| DEF

    G2 -->|Yes| D1{"Broad question<br/>or specific?"}
    D1 -->|Broad| DASH["DASHBOARD<br/>several panels, still one planner call<br/>findings computed in Python"]
    D1 -->|Specific| SQL["Model proposes SQL"]
    DASH --> G3

    SQL --> G3{"GATE 3 — the guard<br/>One statement · SELECT only<br/>every column resolved · read-only"}
    G3 -->|Fails, 1st time| RP["Repair once<br/>guard error fed back"]
    RP --> G3
    G3 -->|Fails again| REF
    G3 -->|Passes| EX["Execute<br/>DuckDB · external access disabled"]

    EX --> NAR["Model writes the sentence"]
    NAR --> G4{"GATE 4<br/>Is every number in it<br/>actually in the rows?"}
    G4 -->|No| FB["Discard it<br/>deterministic fallback"]
    G4 -->|Yes| CG

    FB --> CG{"chart_guard<br/>Do the spec's fields exist<br/>in the result?"}
    CG -->|No| TBL["Table only<br/>no broken chart"]
    CG -->|Yes| CARD

    TBL --> CARD(["ANSWER<br/>sentence · table · chart · the SQL that ran"])
    CARD --> AUD[("Audit log — one line per turn<br/>route · SQL · rows · model · timing · definitions")]
    CHAT --> AUD
    REF --> AUD
    CLR --> AUD

    classDef gate fill:#e4e7f5,stroke:#3d4a8c,stroke-width:2px,color:#191c1f
    classDef stop fill:#f6e6e4,stroke:#b8322a,stroke-width:2px,color:#191c1f
    classDef ask fill:#f6eeda,stroke:#8a6414,stroke-width:2px,color:#191c1f
    classDef go fill:#e2ede8,stroke:#2e6455,stroke-width:2px,color:#191c1f

    class D0,D1,G1,G2,G3,G4,CG gate
    class REF,FB,TBL stop
    class CLR,DEF,CHAT ask
    class SQL,EX,DASH,CARD go
    class SC stop
```

---

## What each gate is for

**Gate 1 — answerable at all?** The first question is not *what is the SQL*, it is
*can these columns answer this*. "Why is attrition going up" is causal; the sheet
holds statuses and dates, not causes. It refuses and says what is missing rather
than inventing a proxy.

**Gate 2 — is every term defined?** "Top performers" — top by what? "Headcount" —
including leavers? Those live in someone's head, not in the data. It asks, with
readings that name real columns, and the choice is pinned for the session and
shown on every answer that depends on it.

**Gate 3 — the guard.** The model has written SQL and it still does not run.
Parsed into a syntax tree, every column resolved against the real schema, one
statement, SELECT only, row cap. Fail once and the error goes back for a repair;
fail twice and you get an honest refusal instead of a broken query.

A read-only DuckDB connection is not a security boundary — `read_csv_auto` still
reads any path on disk and `COPY ... TO` still writes files — so external access
is disabled as well.

**Gate 4 — check the model's homework.** The query ran, so the numbers are real,
but the model still writes the sentence about them. Every number in it must appear
in the returned rows. If one does not, the sentence is discarded for a
deterministic fallback. Years, dates and figures from the question are context; an
invented total fails.

**And the same pattern for charts.** The model authors the Vega-Lite spec, and
`chart_guard` checks every field against the columns the query actually returned.
Invalid Vega-Lite renders a blank chart instead of throwing, so that failure would
otherwise be silent.

---

## Three things the diagram simplifies

**Gates 1 and 2 are decided inside the single planner call**, not as separate model
calls. They are drawn as separate decisions because that is how the logic reads,
not because they cost separate requests.

**The router sits behind `planner.plan`.** Every free tier is rate-limited low
enough to hit inside one demo — Groq 30 requests a minute, OpenRouter's free models
20 a minute and 50 a day. When one provider is busy the router moves to the next
rather than surfacing "your question was never answered."

**A dashboard is several answers in one turn.** Each panel carries its own SQL
through Gate 3 independently, so one bad panel cannot abort the others, and every
finding is computed in Python from the returned rows.

**`endpoint_guard` is not on this path.** It runs when a custom provider endpoint
is configured, not per question: a user-supplied URL is untrusted input in the same
way generated SQL is, so it gets scheme checks, a resolved-address check, no
redirects, and a port allowlist.

---

The diagram renders on GitHub as-is. Delete the `classDef` and `class` lines to let
Mermaid use its own theme.
