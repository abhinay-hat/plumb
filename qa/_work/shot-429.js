async (page) => {
  const leak =
    'The model did not return a usable plan: groq returned 429: {"error":{"message":"Rate limit reached for model `openai/gpt-oss-20b` in organization `org_01kdcydac3fambxx0knkva42hj` service tier `on_demand` on tokens per minute (TPM): Limit 8000, Used 3211, Requested 4828. Please try again in 292.5ms. Need more tokens? Upgrade to Dev Tier today at https://console.groq.com/settings/billing","type":"tokens","code":"rate_limit_exceeded"}}';
  await page.route("**/api/ask", async (route) => {
    await route.fulfill({
      json: {
        route: "refuse",
        sql: null,
        columns: null,
        rows: null,
        narration: null,
        chart: null,
        clarify_question: null,
        clarify_options: null,
        refuse_reason: leak,
        definitions_applied: {},
        elapsed_ms: 368,
      },
    });
  });
  await page.route("**/api/upload", async (route) => {
    await route.fulfill({
      json: {
        session_id: "x",
        tables: [
          {
            name: "employees",
            row_count: 1,
            columns: [
              { name: "id", dtype: "BIGINT", null_count: 0, distinct_count: 1, samples: ["1"] },
            ],
          },
        ],
      },
    });
  });
  await page.getByLabel("Upload spreadsheet").setInputFiles(
    "/Users/padidamabhinay/Projects/Personal/career/Builds/plumb/fixtures/departments.csv",
  );
  await page.getByText("1 table").waitFor();
  await page.getByLabel("Question").fill("ping");
  await page.getByRole("button", { name: "Ask" }).click();
  await page.getByText("Out of range").waitFor();
  await page.locator("article").last().screenshot({
    path: "/Users/padidamabhinay/Projects/Personal/career/Builds/plumb/qa/screenshots/LEAK-groq-429-org-id.png",
  });
  return "ok";
}
