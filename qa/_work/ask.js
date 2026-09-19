async (page) => {
  const q = page.__nextQuestion;
  const input = page.getByLabel("Question");
  await input.fill(q);
  await page.getByRole("button", { name: "Ask" }).click();
  await page.waitForFunction(
    () => {
      const stamps = [...document.querySelectorAll(".stamp")].map((el) =>
        (el.textContent || "").trim().toLowerCase(),
      );
      return stamps.some((t) =>
        ["answer", "method", "out of range"].includes(t),
      );
    },
    { timeout: 90000 },
  );
  return page.__asks[page.__asks.length - 1] || "no-capture";
}
