// Records docs/demo-v2.webm: a real run of the app from an empty library (live AI model, no mocks).
// Run from frontend\ with the app up:  node ..\scripts\record-demo.cjs <folder with sample files>
// Writes docs/demo-v2-marks.json (seconds where the AI wait starts/ends) so the wait can be sped up.
const { createRequire } = require("node:module");
const { chromium } = createRequire(require("node:path").resolve(__dirname, "../frontend/package.json"))("@playwright/test");
const path = require("node:path");
const fs = require("node:fs");

const SRC = process.argv[2];
const FILES = ["dig-03-fsa-data-collection-spreadsheet.xlsx", "fin-02-abattoir-financial-support-consultation.pdf",
  "fin-03-meat-charges-discount-estimator-2026-27.xlsx", "hyg-02-fhrs-appeal-form-england.docx", "hyg-03-haccp-model-plan.docx",
  "hyg-05-sfbb-presentation-level1.pptx", "lab-03-allergy-alert-template.docx", "wrk-01-fsa-diversity-report-2020.pdf",
  "wrk-03-fsa-workforce-mi-oct-2024.xlsx"].map((f) => path.join(SRC, f));
const OUT = path.resolve(__dirname, "../docs");
const W = 1280, H = 800;

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: OUT, size: { width: W, height: H } }, acceptDownloads: true });
  const page = await ctx.newPage();
  const t0 = Date.now();
  const now = () => (Date.now() - t0) / 1000;
  const marks = {};
  const wait = (ms) => page.waitForTimeout(ms);
  const cap = async (text) => {
    await page.evaluate((t) => {
      let el = document.getElementById("demo-cap");
      if (!el) {
        el = document.createElement("div"); el.id = "demo-cap";
        el.style.cssText = "position:fixed;left:50%;bottom:28px;transform:translateX(-50%);z-index:9999;background:#17171c;color:#fff;padding:12px 22px;border-radius:32px;font:500 17px Inter,system-ui,sans-serif;box-shadow:0 6px 24px rgba(0,0,0,.25);max-width:86vw;text-align:center;pointer-events:none";
        document.body.appendChild(el);
      }
      el.textContent = t;
    }, text);
  };
  const smooth = (y) => page.evaluate((y) => window.scrollTo({ top: y, behavior: "smooth" }), y);

  // 1. Home
  await page.goto("http://localhost:3000/"); await wait(1500);
  await cap("DocMap: office files to Markdown, sorted by business theme. Runs on your PC.");
  await wait(3500);
  await smooth(330); await cap("Step 1: drop files. 9 real Food Standards Agency files: PDF, Word, Excel, PowerPoint.");
  await wait(2000);
  await page.getByTestId("file-input").setInputFiles(FILES);
  await page.getByTestId("convert").waitFor({ state: "visible" });
  await page.waitForFunction(() => !document.querySelector('[data-testid="convert"]').disabled, null, { timeout: 60000 });
  await wait(1500);

  // 2. Convert only
  await smooth(700); await cap("Step 2a: Convert to Markdown. No AI model, nothing leaves the PC.");
  await wait(2000);
  await page.getByTestId("convert").click();
  await page.getByTestId("file-list").waitFor({ timeout: 180000 });
  await wait(1200);
  await page.evaluate(() => { const el = document.querySelector('[data-testid="downloads"]'); window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - 110, behavior: "smooth" }); });
  await cap("Step 3: every file has its own Download button, plus Download all (.zip) and Open folder.");
  await wait(4500);

  // 3. Convert and find themes (live AI)
  await smooth(700); await cap("Step 2b: Convert and find themes. The AI model (NVIDIA NIM here) reads every document.");
  await wait(2500);
  await page.getByTestId("process").click();
  marks.waitStart = now();
  // the convert job also ended at 100%, so wait for the process stages to appear first
  await page.waitForFunction(() => document.querySelector('[data-stage="induce"]') && /\b100%/.test(document.querySelector('[data-testid="progress-text"]')?.textContent || ""), null, { timeout: 900000, polling: 1000 });
  marks.waitEnd = now();
  await cap("Done. The AI proposed business themes and linked each file to them, with evidence.");
  await wait(3500);

  // 4. Library
  await page.goto("http://localhost:3000/"); await wait(1500);
  await page.getByText("Your library").scrollIntoViewIfNeeded(); await wait(500);
  await cap("Your library: themes found, links to check, and size warnings. Large sheets keep every row.");
  await wait(4500);

  // 5. Map
  await page.goto("http://localhost:3000/map"); await wait(2500);
  await cap("The map: documents (left) linked to the themes the AI found. Click a link to check it.");
  await wait(4000);
  const edge = page.locator(".react-flow__edge").first();
  if (await edge.count()) { await edge.click({ force: true }); await wait(2500); }

  // 6. Review
  await page.goto("http://localhost:3000/review"); await wait(2000);
  await cap("Review queue: least certain links first, each with the passages behind it. Accept, reject or move.");
  await wait(4500);
  if (await page.getByTestId("accept").count()) { await page.getByTestId("accept").first().click(); await wait(2000); }
  await cap("A human decision is never overwritten by a later AI run.");
  await wait(3000);

  // 7. A document
  await page.goto("http://localhost:3000/docs"); await wait(1500);
  const link = page.locator("a[href^='/docs/']").first();
  if (await link.count()) { await link.click(); await wait(2500); }
  await cap("Each document: its Markdown, token counts, theme links with evidence, and Download .md.");
  await wait(3000); await smooth(900); await wait(3000);

  // 8. Export
  await page.goto("http://localhost:3000/"); await wait(1200);
  await page.getByTestId("export-open").click(); await wait(2500);
  await cap("Export: one Markdown pack per theme. Send an AI only the theme you need, not the whole library.");
  await wait(5000);
  await page.keyboard.press("Escape"); await wait(800);

  // 9. Settings
  await page.goto("http://localhost:3000/settings"); await wait(2500);
  await cap("Settings: NVIDIA NIM (cloud) or a local model with Ollama, with a live status check.");
  await wait(3000);
  await page.getByTestId("choose-local").click(); await wait(3500);
  await cap("Local mode: install Ollama, pull two models, and nothing leaves your PC.");
  await wait(3500);
  await page.getByTestId("choose-nim").click(); await wait(1500);

  marks.end = now();
  const video = page.video();
  await ctx.close(); await browser.close();
  const raw = await video.path();
  fs.renameSync(raw, path.join(OUT, "demo-v2.webm"));
  fs.writeFileSync(path.join(OUT, "demo-v2-marks.json"), JSON.stringify(marks, null, 1));
  console.log("marks", marks);
})();
