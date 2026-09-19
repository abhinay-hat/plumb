async (page) => {
  await page.getByText("Recording", { exact: true }).waitFor({ timeout: 15000 }).catch(() => {});
  await page.getByText("Recording", { exact: true }).waitFor({ state: "hidden", timeout: 90000 });
  const last = page.__asks && page.__asks[page.__asks.length - 1];
  if (!last) return { captured: false };
  const b = last.body || {};
  return {
    question: last.question,
    status: last.status,
    route: b.route,
    narration: b.narration,
    sql: b.sql,
    columns: b.columns,
    rows: b.rows,
    refuse_reason: b.refuse_reason,
    clarify_question: b.clarify_question,
    clarify_options: b.clarify_options,
    definitions_applied: b.definitions_applied,
    elapsed_ms: b.elapsed_ms,
  };
}
