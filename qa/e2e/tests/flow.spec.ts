import { test, expect } from "@playwright/test";
import { stubBackend, uploadStubWorkbook } from "../helpers/stub";

test.describe("flow", () => {
  test("reload after upload returns to the empty state", async ({ page }) => {
    await stubBackend(page);
    await uploadStubWorkbook(page);
    await expect(page.getByText("3 tables")).toBeVisible();
    await page.reload();
    await expect(page.getByText("no file")).toBeVisible();
    await expect(page.getByText("Upload a sheet. Ask in English. Check the work.")).toBeVisible();
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

  test("composer is disabled until a file is loaded", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByLabel("Question")).toBeDisabled();
    await expect(page.getByRole("button", { name: "Ask" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Audit" })).toBeDisabled();
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
