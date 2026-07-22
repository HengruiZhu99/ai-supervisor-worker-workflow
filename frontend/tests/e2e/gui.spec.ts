import { expect, test } from "@playwright/test";

let browserErrors: string[] = [];

test.beforeEach(async ({ page }) => {
  browserErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error" || message.type() === "warning")
      browserErrors.push(message.text());
  });
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto("/");
});

test.afterEach(() => {
  expect(browserErrors).toEqual([]);
});

test("Solo is default and advanced orchestration is progressive", async ({
  page,
}) => {
  await expect(
    page.getByRole("banner", { name: "Project identity" }),
  ).toBeVisible();
  await expect(page.getByRole("radio", { name: /Solo TDD/ })).toBeChecked();
  await expect(page.getByText(/checkout [a-f0-9]{8}/)).toBeVisible();
  await expect(page.getByText(/worktree [a-f0-9]{8}/)).toBeVisible();
  const details = page.locator("details");
  await expect(details).not.toHaveAttribute("open", "");
  await page.getByRole("radio", { name: /Autonomous Program/ }).check();
  await expect(details).toHaveAttribute("open", "");
  await page.getByRole("button", { name: "Color theme: system" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});

test("run mutation, stale revision, SSE reset, and responsive layout", async ({
  page,
}) => {
  const objective = `Playwright bounded task ${Date.now()}`;
  await page.getByLabel("Describe the outcome").fill(objective);
  await page.getByRole("button", { name: /Create paused run/ }).click();
  const runCard = page.locator("article").filter({
    has: page.getByRole("heading", { name: objective }),
  });
  await expect(runCard).toBeVisible();
  await expect(runCard.getByRole("button", { name: "Resume" })).toBeVisible();
  await expect(
    runCard.getByRole("button", { name: "Export handoff" }),
  ).toBeVisible();

  const staleStatus = await page.evaluate(async () => {
    const snapshot = await (await fetch("/api/v1/snapshot")).json();
    const run = snapshot.runs.at(-1);
    const token = document
      .querySelector('meta[name="aiflow-token"]')
      ?.getAttribute("content");
    const response = await fetch(`/api/v1/runs/${run.run_id}/stop`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-AIFLOW-Token": token ?? "",
      },
      body: JSON.stringify({
        expected_revision: run.state_revision - 1,
        checkout_id: snapshot.project.checkout_id,
      }),
    });
    return response.status;
  });
  expect(staleStatus).toBe(409);
  browserErrors = browserErrors.filter(
    (message) => !message.includes("409 (Conflict)"),
  );

  const resetEvent = await page.evaluate(async () => {
    const response = await fetch("/api/v1/events", {
      headers: { "Last-Event-ID": "invalid" },
    });
    return response.text();
  });
  expect(resetEvent).toContain("event: reset");

  await page.setViewportSize({ width: 390, height: 844 });
  const widths = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
  }));
  expect(widths.document).toBe(widths.viewport);
  await expect(
    page.getByRole("banner", { name: "Project identity" }),
  ).toBeVisible();
});

test("two disposable project servers remain isolated", async ({
  page,
  context,
}) => {
  const objective = `First project only ${Date.now()}`;
  const first = await page.evaluate(async () =>
    (await fetch("/api/v1/snapshot")).json(),
  );
  await page.getByLabel("Describe the outcome").fill(objective);
  await page.getByRole("button", { name: /Create paused run/ }).click();
  await expect(page.getByRole("heading", { name: objective })).toBeVisible();

  const secondPage = await context.newPage();
  await secondPage.goto("http://127.0.0.1:8878/");
  const second = await secondPage.evaluate(async () =>
    (await fetch("/api/v1/snapshot")).json(),
  );
  expect(second.project.checkout_id).not.toBe(first.project.checkout_id);
  expect(
    second.runs.some(
      (run: { objective?: string }) => run.objective === objective,
    ),
  ).toBe(false);
  await expect(
    secondPage.getByText(
      "No runs yet. Your first run starts paused and resumable.",
    ),
  ).toBeVisible();
  await secondPage.close();
});
