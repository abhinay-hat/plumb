import type { Page } from "@playwright/test";
import { ASKS, SESSION_ID, TABLES } from "./captured";

const STUB_SUGGESTIONS = [
  "How many employees in each department?",
  "What's the average base salary inr by department?",
  "Who are the top employees by base salary inr?",
];

export async function stubBackend(page: Page) {
  await page.route("**/api/health", async (route) => {
    await route.fulfill({ json: { status: "ok" } });
  });

  await page.route("**/api/session", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({ json: { session_id: SESSION_ID } });
  });

  await page.route("**/api/upload", async (route) => {
    await route.fulfill({
      json: { session_id: SESSION_ID, tables: TABLES, suggestions: STUB_SUGGESTIONS },
    });
  });

  await page.route("**/api/session/*/suggestions", async (route) => {
    await route.fulfill({ json: { suggestions: STUB_SUGGESTIONS } });
  });

  await page.route("**/api/ask", async (route) => {
    const posted = route.request().postDataJSON() as { question?: string };
    const question = (posted?.question ?? "").trim();
    const body = ASKS[question] ?? {
      route: "refuse",
      sql: null,
      columns: null,
      rows: null,
      narration: null,
      chart: null,
      clarify_question: null,
      clarify_options: null,
      refuse_reason: `stub has no plan for: ${question}`,
      definitions_applied: {},
      elapsed_ms: 1,
    };
    await route.fulfill({ json: body });
  });

  await page.route("**/api/session/*/settle", async (route) => {
    const posted = route.request().postDataJSON() as { term?: string; definition?: string };
    await route.fulfill({
      json: { definitions: { [posted.term ?? "definition"]: posted.definition ?? "" } },
    });
  });

  await page.route("**/api/session/*/schema", async (route) => {
    await route.fulfill({ json: TABLES });
  });

  await page.route("**/api/session/*/audit", async (route) => {
    await route.fulfill({ json: [] });
  });
}

export async function uploadStubWorkbook(page: Page) {
  await page.goto("/");
  await page.getByLabel("Upload spreadsheet").setInputFiles({
    name: "northwind_hr_analytics.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: Buffer.from("stub"),
  });
  await page.getByText("3 tables").waitFor();
}

export async function ask(page: Page, question: string) {
  await page.getByLabel("Question").fill(question);
  await page.getByRole("button", { name: "Ask" }).click();
  await page.getByText("Recording").waitFor({ state: "hidden", timeout: 15_000 });
}
