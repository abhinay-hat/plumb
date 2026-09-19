import { test, expect } from "@playwright/test";
import { keepSessionStorageOnNextLoad, installFreshSessionStorage } from "../helpers/storage";
import { stubBackend, uploadStubWorkbook } from "../helpers/stub";

test.describe("flow", () => {
  test.beforeEach(async ({ page }) => {
    await installFreshSessionStorage(page);
  });

  test("reload after upload restores the sheet in this tab", async ({ page }) => {
    await stubBackend(page);
    await uploadStubWorkbook(page);
    await expect(page.getByText("3 tables")).toBeVisible();
    await keepSessionStorageOnNextLoad(page);
    await page.reload();
    await expect(page.getByText("3 tables")).toBeVisible();
    await expect(page.getByText("Ask in English. Check the SQL.")).toBeVisible();
  });

  test("new session clears the sheet and conversation", async ({ page }) => {
    await stubBackend(page);
    await uploadStubWorkbook(page);
    await expect(page.getByText("3 tables")).toBeVisible();
    await page.getByRole("button", { name: "New session" }).click();
    await expect(page.getByText("no file")).toBeVisible();
    await expect(page.getByText("Say hi. Or upload a sheet.")).toBeVisible();
  });

  test("a second tab does not inherit the session", async ({ page, context }) => {
    await stubBackend(page);
    await uploadStubWorkbook(page);
    const other = await context.newPage();
    await stubBackend(other);
    await other.goto("/");
    await expect(other.getByText("no file")).toBeVisible();
    await expect(page.getByText("3 tables")).toBeVisible();
    await other.close();
  });

  test("composer accepts chat before a file is loaded", async ({ page }) => {
    await stubBackend(page);
    await page.route("**/api/ask", async (route) => {
      await route.fulfill({
        json: {
          route: "chat",
          reply: "Hi — upload a spreadsheet when you are ready to ask about data.",
          sql: null,
          columns: null,
          rows: null,
          narration: null,
          chart: null,
          clarify_question: null,
          clarify_options: null,
          refuse_reason: null,
          definitions_applied: {},
          elapsed_ms: 12,
          provider: "ollama",
          model: "stub",
          endpoint_host: null,
        },
      });
    });
    await page.goto("/");
    await expect(page.getByLabel("Question")).toBeEnabled({ timeout: 10_000 });
    await page.getByLabel("Question").fill("Hi");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(
      page.getByText("Hi — upload a spreadsheet when you are ready to ask about data."),
    ).toBeVisible();
  });

  test("recovers when the API no longer has the session", async ({ page }) => {
    let askCalls = 0;
    await stubBackend(page);
    await page.route("**/api/ask", async (route) => {
      askCalls += 1;
      if (askCalls === 1) {
        await route.fulfill({
          status: 404,
          contentType: "application/json",
          body: JSON.stringify({
            code: "session_not_found",
            message: "no session stale-id",
          }),
        });
        return;
      }
      await route.fulfill({
        json: {
          route: "chat",
          reply: "Hi — session recovered.",
          sql: null,
          columns: null,
          rows: null,
          narration: null,
          chart: null,
          clarify_question: null,
          clarify_options: null,
          refuse_reason: null,
          definitions_applied: {},
          elapsed_ms: 8,
          provider: "ollama",
          model: "stub",
          endpoint_host: null,
        },
      });
    });
    await page.goto("/");
    await expect(page.getByLabel("Question")).toBeEnabled({ timeout: 10_000 });
    await page.getByLabel("Question").fill("Hi");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByText("Hi — session recovered.")).toBeVisible();
    expect(askCalls).toBe(2);
  });

  test("Ask is disabled while a turn is in flight", async ({ page }) => {
    await stubBackend(page);
    await page.route("**/api/ask", async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.fulfill({
        json: {
          route: "answer",
          sql: "SELECT 1 AS n LIMIT 1000",
          columns: ["n"],
          rows: [[1]],
          narration: "1 rows returned.",
          chart: null,
          clarify_question: null,
          clarify_options: null,
          refuse_reason: null,
          definitions_applied: {},
          elapsed_ms: 1500,
        },
      });
    });
    await uploadStubWorkbook(page);
    await page.getByLabel("Question").fill("ping");
    await page.getByRole("button", { name: "Ask" }).click();
    await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
    await expect(page.getByText("Recording")).toBeVisible();
  });
});
