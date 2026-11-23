# DocMap: assessment submission

Task: Option 1, build a small application with an AI development tool.

DocMap is a local web app that turns office files (Word, Excel, PowerPoint, PDF) into clean Markdown, has an AI model sort them by business theme, and lets a person check and correct each link between a file and a theme. You can download every Markdown file, or export one pack per theme to give to an AI model.

## 1. Working application

| What | Where |
|---|---|
| Source code | https://github.com/EgiBal/docmap-v2 |
| Screen recording (about 2 minutes, a real run from an empty library with a live AI model) | [docs/demo-v2.mp4](docs/demo-v2.mp4) |
| Run it yourself (Windows) | Double-click `Start DocMap.bat`. It opens http://localhost:3000. You need Python with [uv](https://docs.astral.sh/uv/) and Node.js. See the [README](README.md#how-to-run-it). |

In the app you can:

1. Upload many files at once into a large drop zone.
2. Convert them to Markdown on your PC, with no AI involved, and download each `.md` file, all of them as a zip, or open the folder.
3. Convert and find themes: the AI model reads every document, proposes 4 to 7 business themes and links each file to its themes, with a confidence score and the passages that support the link.
4. Review the links on a map or in a queue that shows the least certain links first, and accept, reject or move each one. A later AI run never overwrites a decision you made.
5. Export one Markdown pack per theme.
6. Choose the AI model in Settings: NVIDIA NIM in the cloud, or a local model through Ollama. Each has setup steps and a live check that shows whether it is ready.

Without your own files, click "Try the 22 sample files" on the home page.

## 2. AI tools used

I built DocMap with Claude Code, Anthropic's command-line coding agent. I gave it one starting prompt with my idea (the full prompt is in the [README](README.md#how-ai-built-this)), and it planned and wrote the application, asking me whenever a decision was mine.

| Tool | How it helped |
|---|---|
| Claude Code on Claude Opus | Turned the idea into a plan with milestones, wrote a brief for each task, checked the results, ran the tests and asked me to decide at each milestone. |
| Claude Sonnet subagents, started by Claude Code | Studied the four open-source repositories I named, then wrote the converter, the AI pipeline, the API, the interface, the export and the tests. Up to six worked at the same time, each on its own list of files. One reviewed the code independently, one wrote tests with broken and unusual files, and one checked screenshots of the interface for layout problems. |
| Task notes | Every agent wrote a note on what it did and where to resume, so the work continued across sessions without losing track. |
| Playwright, driven by Claude Code | Browser tests, screenshots for design review, and the recorded demo (`scripts/record-demo.cjs`). |
| awesome-design-md and humanizer | Cohere's `DESIGN.md` from [awesome-design-md](https://github.com/VoltAgent/awesome-design-md) was the specification for the final visual style. The [humanizer](https://github.com/blader/humanizer) guidelines were used to edit the README and this document. |
| AI inside the product | NVIDIA NIM (`nemotron-3.5-lightning-30b-a3b` writes, `nemotron-3.5-embed-1b` compares) or Ollama on the PC (`gemma3:4b` and `nomic-embed-text`). |

My part was the idea and its goals, the starting repositories, and the product decisions: the interface library, letting the AI find the themes by itself, NIM with a local option, and the rule that every spreadsheet row is converted and the user is only warned about size. After testing the app myself I asked for a one-click start, a larger upload area, clearer downloads and the model settings page, and I chose the final design from two variants. The README lists these points in full.

## 3. Technical explanation

### How the application works

1. Convert. Each file goes through anydoc, and through markitdown if anydoc cannot read it. A slim pass removes image links, empty cells and repeated headers but keeps headings and tables. Scanned pages without a text layer are flagged as needing OCR. Password-protected files, hidden sheets and unsupported types each get a clear message.
2. Profile. The AI model writes a two-sentence business summary of each document. Document text is wrapped in `<document>` tags, so text inside a file is not treated as an instruction.
3. Find themes. One AI call proposes 4 to 7 themes for the whole set, each with a name, a description and synonyms. Batched calls then assign each file to its themes. An embedding similarity check runs next to the model's answer, and links where the two disagree go to the top of the review queue.
4. Store. Results go into SQLite. Themes keep their IDs between runs by matching on embedding similarity, and links a person has accepted, rejected or moved are never overwritten.
5. Review and export. The interface shows a map (React Flow) and a review queue with the supporting passages. The export writes one Markdown file per theme plus an index, and warns when a pack is larger than 128,000 tokens.

### Technologies

The backend is Python 3.12 with uv, FastAPI, SQLModel on SQLite, anydoc, markitdown, openpyxl, tiktoken, NumPy and SciPy, and httpx. It has one OpenAI-compatible client per model role, with retries and disk caches. The interface is Next.js 16 with React 19, TypeScript, Tailwind CSS v4, shadcn/ui with Base UI, kokonutui components and React Flow. Tests are pytest for the backend (API, converter, unusual files, storage rules, scoring) and Playwright for the browser.

### Approach

I started with a plan and small tasks, each with one owner, a fixed set of files and a written note, so every step could be checked. I measured the results instead of judging by eye: I labelled the themes of 22 files by hand, and I kept a second set of 19 files from another organisation apart and never used it while building the method. I scored the AI against both sets, also with the file names hidden. On the second set the AI's themes reached an F1 score of 0.93. For tokens, one theme's pack was at least 98% smaller than the whole library for 4 of the 5 themes. The AI proposes and the person decides, so the review screen is the centre of the app.

## 4. Challenges and solutions

| Challenge | Solution |
|---|---|
| Starting the app on Windows. Double-clicking `run.ps1` made Windows ask which program should open it, because Windows does not run PowerShell scripts by default. Running it from a terminal opened two extra PowerShell windows (API and interface) that had to stay open. | `Start DocMap.bat` runs on a double-click. It starts PowerShell with the execution policy set for that call only, starts the API and the interface as hidden background processes with their logs in `data\logs\`, waits until both answer and opens the browser. `Stop DocMap.bat` stops both. The interface is rebuilt only when its code has changed, so normal starts take seconds. |
| Very large spreadsheets. One sample sheet is 12 MB, about 8 million tokens, more than any AI model can take at once. | Every row is still converted, because cutting rows without telling the user would lose data. The app marks the file as too large for most models and shows the warning in the library and the export. An optional spreadsheet summary at export (statistics and the first 20 rows) is available but off by default. |
| Grouping files by subject instead of by file type. Grouping text chunks by similarity put all the spreadsheets together and all the slides together. | The AI now writes a short business summary of each document first, proposes the themes for the whole set from those summaries, and then assigns the files. An embedding check flags links where the model and the similarity score disagree, and those go to the top of the review queue. A hidden-file-name mode and a separate test set confirm that the method generalises. |
| Differences between model APIs. The NIM writing model needs its reasoning mode turned off to return plain JSON, the embedding model needs an `input_type`, and the local models need text prefixes and a warm-up call. | Each model role has its own client and settings, with presets for NIM and Ollama. The client handles retries and fallback models and caches answers on disk, so a repeat run takes under a second. |

More detail on the design, the token tests and how to run everything is in the [README](README.md) and [docs/architecture.md](docs/architecture.md).
