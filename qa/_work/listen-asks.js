async (page) => {
  page.__asks = [];
  page.on("response", async (res) => {
    if (res.url().includes("/api/ask") && res.request().method() === "POST") {
      try {
        const body = await res.json();
        const q = JSON.parse(res.request().postData() || "{}").question;
        page.__asks.push({ question: q, status: res.status(), body });
      } catch (e) {
        page.__asks.push({ error: String(e), url: res.url(), status: res.status() });
      }
    }
  });
  return "listener-ready";
}
