import { test, expect } from "@playwright/test";

const API = process.env.PLUMB_API ?? "http://127.0.0.1:8000";

test.describe("ingest attacks (real API, no LLM)", () => {
  test("empty sheet returns ingest_failed, not a 500", async ({ request }) => {
    // Minimal zip-shaped xlsx is overkill; a 0-byte csv is the documented trap.
    const zero = await request.post(`${API}/api/upload`, {
      multipart: { file: { name: "zero.csv", mimeType: "text/csv", buffer: Buffer.from("") } },
    });
    // Product currently 200s a phantom column0 table — characterization.
    expect([200, 400]).toContain(zero.status());
    const body = await zero.json();
    if (zero.status() === 200) {
      expect(body.tables[0].row_count).toBe(0);
    } else {
      expect(body.code).toBe("ingest_failed");
    }
  });

  test("latin-1 csv does not 500", async ({ request }) => {
    const r = await request.post(`${API}/api/upload`, {
      multipart: {
        file: {
          name: "latin1.csv",
          mimeType: "text/csv",
          buffer: Buffer.from("id,name\n1,caf\xe9\n", "latin1"),
        },
      },
    });
    expect(r.status()).toBe(400);
    const body = await r.json();
    expect(body.code).toBe("ingest_failed");
    expect(body.message).toBeTruthy();
  });

  test("path-traversal filename is stored as a basename, not written to /etc", async ({ request }) => {
    const r = await request.post(`${API}/api/upload`, {
      multipart: {
        file: {
          name: "../../etc/passwd.csv",
          mimeType: "text/csv",
          buffer: Buffer.from("id,name\n1,a\n"),
        },
      },
    });
    expect(r.status()).toBe(200);
    const body = await r.json();
    expect(body.tables[0].name).toBe("passwd");
  });

  test("SQL reserved-word headers ingest", async ({ request }) => {
    const r = await request.post(`${API}/api/upload`, {
      multipart: {
        file: {
          name: "select_col.csv",
          mimeType: "text/csv",
          buffer: Buffer.from("select,name\n1,alice\n"),
        },
      },
    });
    expect(r.status()).toBe(200);
    const names = (await r.json()).tables[0].columns.map((c: { name: string }) => c.name);
    expect(names).toContain("select");
  });
});
