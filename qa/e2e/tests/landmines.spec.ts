import { test, expect } from "@playwright/test";
import { ask, stubBackend, uploadStubWorkbook } from "../helpers/stub";

test.describe("landmines (LLM stubbed with live-captured payloads)", () => {
  test.beforeEach(async ({ page }) => {
    await stubBackend(page);
    await uploadStubWorkbook(page);
  });

  test("LM1: average salary presents the naive historical mean as fact", async ({ page }) => {
    await ask(page, "What's the average salary?");
    await expect(page.getByText("Answer", { exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: /3050227/ })).toBeVisible();
    await expect(page.getByText(/historical|latest row|per employee/i)).toHaveCount(0);
    await page.getByText("Show SQL").click();
    await expect(page.locator("pre")).toContainText('AVG("northwind_hr_analytics_compensation"."base_salary_inr")');
    await expect(page.locator("pre")).not.toContainText("QUALIFY");
  });

  test("LM2: location group-by splits Hyderabad / hyderabad", async ({ page }) => {
    await ask(page, "How many employees in each location?");
    await expect(page.getByText("Hyderabad has the highest headcount with 183 employees.")).toBeVisible();
    await expect(page.getByRole("cell", { name: "183" })).toBeVisible();
    await expect(page.getByRole("cell", { name: "hyderabad", exact: true })).toBeVisible();
    await expect(page.getByRole("cell", { name: "4", exact: true })).toBeVisible();
  });

  test("LM3: department group-by then total — 7 nulls billed as a department", async ({ page }) => {
    await ask(page, "How many employees in each department?");
    await expect(page.getByText(/smallest department has 7/)).toBeVisible();
    await ask(page, "How many employees are there?");
    await expect(page.getByText("640 employees")).toBeVisible();
    const named = 195 + 102 + 36;
    expect(named).not.toBe(640);
  });

  test("LM4: average rating does not disclose 52 excluded nulls", async ({ page }) => {
    await ask(page, "What's the average performance rating?");
    const card = page.locator("article").last();
    await expect(card.getByRole("cell", { name: /3\.1935/ })).toBeVisible();
    await expect(card.getByText(/null|1,248|1248|1,300|1300/i)).toHaveCount(0);
  });

  test("LM5: headcount and attrition clarify instead of guessing", async ({ page }) => {
    await ask(page, "What's our headcount?");
    await expect(page.getByText("Method")).toBeVisible();
    await expect(page.getByRole("button", { name: "Total employees" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Active employees" })).toBeVisible();

    await ask(page, "What's our attrition rate?");
    await expect(page.getByText("How would you like to define attrition rate?")).toBeVisible();
    await expect(page.getByRole("button", { name: /average headcount/i })).toBeVisible();
  });

  test("LM5: top performers does clarify", async ({ page }) => {
    await ask(page, "Who are our top performers?");
    await expect(page.getByText("Method")).toBeVisible();
    await expect(page.getByText("plumb will not guess")).toBeVisible();
    await expect(page.getByRole("button", { name: /Highest latest performance_rating/ })).toBeVisible();
  });
});
