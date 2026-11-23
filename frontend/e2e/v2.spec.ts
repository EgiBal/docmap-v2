import { test, expect } from "@playwright/test";
import path from "node:path";

// v2 flow without any AI model: upload -> Convert to Markdown -> download. Plus the Settings page.
const SAMPLE = path.resolve(__dirname, "../../corpus/raw/dig-02-lidar-technical-guide.docx");
const API = "http://localhost:8000";

test("upload, convert only, and download the Markdown", async ({ page, request }) => {
  await page.goto("/");
  await expect(page.getByTestId("dropzone")).toBeVisible();
  const box = await page.getByTestId("dropzone").boundingBox();
  expect(box!.height).toBeGreaterThanOrEqual(260);                      // large drop target

  await page.getByTestId("file-input").setInputFiles(SAMPLE);
  await expect(page.getByTestId("picked")).toContainText("dig-02-lidar-technical-guide.docx");
  await expect(page.getByTestId("convert")).toBeEnabled({ timeout: 30_000 });
  await page.getByTestId("convert").click();

  const row = page.getByTestId("file-list").getByText("dig-02-lidar-technical-guide.docx.md");
  await expect(row).toBeVisible({ timeout: 90_000 });
  await expect(page.getByTestId("download-all")).toBeVisible();

  const md = await request.get(`${API}/api/files/${encodeURIComponent("dig-02-lidar-technical-guide.docx.md")}`);
  expect(md.status()).toBe(200);
  expect(md.headers()["content-disposition"]).toContain("attachment");
  expect((await md.text()).length).toBeGreaterThan(500);
  expect((await request.get(`${API}/api/files/all.zip`)).status()).toBe(200);
});

test("settings shows both model choices with a live status and the folders", async ({ page }) => {
  await page.goto("/settings");
  await expect(page.getByTestId("choose-nim")).toBeVisible();
  await expect(page.getByTestId("choose-local")).toBeVisible();
  await expect(page.locator('[data-testid^="choose-"][aria-pressed="true"]')).toHaveCount(1);   // settings loaded
  const current = (await page.getByTestId("choose-nim").getAttribute("aria-pressed")) === "true" ? "nim" : "local";
  await expect(page.getByTestId(`status-${current}`)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Converted Markdown")).toBeVisible();
  await expect(page.getByText(/ollama pull|build\.nvidia\.com/).first()).toBeVisible();
});

test("the API refuses bad input", async ({ request }) => {
  expect((await request.get(`${API}/api/files/..%5Cdocmap.db`)).status()).toBe(404);
  expect((await request.post(`${API}/api/settings/nim-key`, { data: { key: "abc" }, headers: { "X-DocMap": "1" } })).status()).toBe(422);
  expect((await request.put(`${API}/api/settings`, { data: { preset: "x" }, headers: { "X-DocMap": "1" } })).status()).toBe(422);
  expect((await request.post(`${API}/api/convert`, { data: {} })).status()).toBe(403);    // no X-DocMap header
});
