"""Eight questions in ninety seconds. Nothing may come back a misleading refusal."""

import json
import sys
import time

import httpx

BASE = "http://127.0.0.1:8000"
QUESTIONS = [
    "How many employees are in each department?",
    "What is the average salary by location?",
    "How many employees were hired in 2024?",
    "How many employees are terminated?",
    "What is the headcount by job level?",
    "How many training records are there per department?",
    "What is the average engagement score by department?",
    "How many open recruitment records are there?",
]

with open("fixtures/northwind_hr_analytics.xlsx", "rb") as fh:
    up = httpx.post(f"{BASE}/api/upload", files={"file": ("northwind_hr_analytics.xlsx", fh)}, timeout=120)
up.raise_for_status()
sid = up.json()["session_id"]
print(f"session {sid}, {len(up.json()['tables'])} tables\n", flush=True)

start = time.perf_counter()
rows = []
for i, q in enumerate(QUESTIONS, 1):
    t0 = time.perf_counter()
    r = httpx.post(f"{BASE}/api/ask", json={"session_id": sid, "question": q}, timeout=180)
    dt = time.perf_counter() - t0
    if r.status_code != 200:
        rows.append((i, q, f"HTTP {r.status_code}", r.text[:120], dt))
        print(f"{i}. [{r.status_code}] {q}\n   {r.text[:200]}", flush=True)
        continue
    b = r.json()
    detail = {
        "answer": lambda: (b.get("narration") or "")[:110],
        "clarify": lambda: (b.get("clarify_question") or "")[:110] + f"  term={b.get('clarify_term')!r}",
        "refuse": lambda: (b.get("refuse_reason") or "")[:140],
        "chat": lambda: (b.get("reply") or "")[:110],
        "error": lambda: f"{b.get('error_code')}: {(b.get('error_message') or '')[:110]}",
    }[b["route"]]()
    rows.append((i, q, b["route"], detail, dt))
    print(f"{i}. [{b['route']}] {q}\n   {detail}   ({dt:.1f}s)", flush=True)

total = time.perf_counter() - start
print(f"\nelapsed: {total:.1f}s for {len(QUESTIONS)} questions", flush=True)
counts = {}
for _, _, route, _, _ in rows:
    counts[route] = counts.get(route, 0) + 1
print("routes:", json.dumps(counts))
bad = [r for r in rows if r[2] == "refuse" and "model did not return" in str(r[3])]
print("misleading refusals (model-failure dressed as a data verdict):", len(bad))
sys.exit(1 if bad else 0)
