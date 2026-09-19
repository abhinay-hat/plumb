import type { Page } from "@playwright/test";

/** Clear sessionStorage on the first navigation of each test, not on reload. */
export async function installFreshSessionStorage(page: Page) {
  await page.addInitScript(() => {
    if (sessionStorage.getItem("__plumb_e2e_keep")) {
      sessionStorage.removeItem("__plumb_e2e_keep");
      return;
    }
    sessionStorage.clear();
  });
}

/** Call before `page.reload()` when the test expects workspace state to survive. */
export async function keepSessionStorageOnNextLoad(page: Page) {
  await page.evaluate(() => sessionStorage.setItem("__plumb_e2e_keep", "1"));
}
