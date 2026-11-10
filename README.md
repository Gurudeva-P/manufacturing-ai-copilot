# Manufacturing AI Copilot

A mobile-friendly FastAPI RAG app for helping a shop-floor supervisor find instructions in the supplied manufacturing PDFs. It returns answers grounded in retrieved excerpts, with document ID, revision, and PDF page citations. QC-SOP-014 Rev 04 is treated as current; Rev 03 is marked superseded and excluded from current operational answers.

**Project thinking:** [THINKING.md](THINKING.md) preserves the independent journey draft and distinguishes it from AI-assisted feedback and suggested reflections.

## User and problem

The assignment describes a supervisor at Kaveri Precision Components' Hosur plant who may need information about a TX-200 alarm, LOTO rules, or incoming inspection. The need to find a correct instruction while an operator or inspector is waiting is a reasonable product assumption, not user-interview evidence. More on the assumed persona and open questions is in [THINKING.md](THINKING.md).

## How it works

1. At app startup, PyPDF extracts text from the four operational PDFs. Layout-aware extraction helps retain table rows, such as the QC lot-size/sampling plan. The fifth PDF, Sample Questions, is a test prompt list and is not indexed as answer evidence.
2. Extracted text is split into line-preserving chunks (about 1,050 characters with overlap) and tagged with document ID, revision, and page.
3. Each chunk and user query gets a local 384-dimensional signed feature-hashing vector. Retrieval ranks chunks using cosine similarity and term coverage, with numeric range matching for questions such as a lot size of 100.
4. Superseded QC-SOP-014 Rev 03 chunks are excluded from current QC answers. If retrieval cannot find adequate supporting evidence, the API abstains before generation.
5. Gemini receives the retrieved chunks, labeled with source metadata, via Google's Interactions API. The prompt requires answers to use only the supplied excerpts and cite the document, revision, and page. The UI displays the generated answer and the supporting source excerpts.

### RAG implementation choices

This project deliberately uses lightweight feature-hashing vectors, not a pretrained neural embedding model. It uses an in-memory Python index, not a persistent vector database. There is no FAISS, ChromaDB, or LangChain dependency. The index is recreated from the PDFs whenever the app starts; this keeps the assignment implementation small and understandable, but is not a design for a large production corpus.

The 100-piece regression followed a real retrieval failure: ordinary PDF extraction split table cells; the semantically generic query terms ranked Rev 04 Page 2 above the sampling plan, and a score cutoff excluded the Page 1 chunk. Layout-mode extraction keeps the table's rows together; numeric interval matching recognizes that 100 falls inside 91–500; related chunks from the same source page are retained. The regression checks the actual Rev 04 Page 1 content, including the 91–500 row and 13 value, rather than hardcoding an answer in the app.

## Features and stack

- Backend: Python, FastAPI, Uvicorn
- PDF text: pypdf with layout extraction
- Retrieval: deterministic feature-hashing vectors, cosine similarity, lexical coverage, and numeric interval matching
- Generation: Gemini Interactions REST API
- UI: plain HTML, CSS, and JavaScript; responsive layout
- Revision handling: document ID/revision/page metadata; Rev 04 supersedes QC-SOP-014 Rev 03
- Safety/reliability: cited source excerpts, abstention on insufficient evidence, explicit error if Gemini is missing or unavailable
- Optional container: Dockerfile and Docker Compose

## Run locally

Requires Python 3.10 or newer.

1. Create a local key file from the template:

       cp .env.example .env

   Edit .env and set GEMINI_API_KEY. GEMINI_MODEL is optional and defaults to gemini-3.5-flash-lite. Never commit .env or paste the key into a public issue/chat.

2. Create the environment, install dependencies, and start FastAPI:

       python3 -m venv .venv
       source .venv/bin/activate
       python -m pip install -r requirements.txt
       uvicorn app.main:app --host 0.0.0.0 --port 8000

Open http://127.0.0.1:8000 on the Mac. API documentation is at http://127.0.0.1:8000/docs. FastAPI binds to all interfaces for the same-Wi-Fi phone demo.

If GEMINI_API_KEY is missing, the answer endpoint returns a clear configuration error. Gemini network/API failures also return an explicit error; retrieved excerpts are not represented as a completed model answer. The secret is loaded from .env at runtime, .env is Git-ignored, and .dockerignore prevents it from entering a Docker build context.

## Docker

Docker Desktop / Engine and the Compose plugin are required. The Dockerfile uses Python 3.12 slim and a non-root app user. Compose forwards port 8000, reads environment values from the local .env, mounts documents read-only, and defines a health check against /api/health. The retrieval index is intentionally in memory and is rebuilt from the mounted PDFs at container startup; there is no vector database volume.

Start and inspect the service:

       docker compose up --build -d
       docker compose ps
       docker compose logs -f copilot
       curl -f http://127.0.0.1:8000/api/health

Stop it with:

       docker compose down

**Verification status:** Docker Desktop and its CLI are present on the Mac, but the current Codex execution environment is denied access to the Docker socket. I could not build or start the container here. The user previously reported seeing Docker Desktop running with no project containers. Treat Docker runtime verification as pending until the commands above succeed in the user's Terminal.

## API

- GET /api/health — process health, chunk count, and whether a Gemini key is configured (never returns the key)
- GET /api/documents — indexed document IDs/revisions and whether each is current
- POST /api/ask — JSON body such as {"question":"What does alarm AL-104 mean and what should the operator do?"}

## Evaluation questions and PDF-grounded answer references

These answer references are checked against the PDFs. They explain the expected grounded content; they are not verbatim transcripts for every question. Automated tests mock Gemini and verify retrieval, sources, and abstention. Manual live Gemini checks observed in this project session are listed after the tables.

### Five supplied questions

| Question | Expected answer reference |
|---|---|
| What is the recommended coolant concentration for the TX-200 CNC turning centre? | 6–8%. MNT-MAN-CNC-02, Rev 02, p. 1, Normal Operating Parameters. |
| The machine is showing alarm AL-104. What does it mean and what should the operator do? | Way lube oil level low. Top up ISO VG 68 oil to MAX and press RESET; the machine can continue after reset. MNT-MAN-CNC-02, Rev 02, p. 2, Common Alarms. |
| Who is allowed to remove a lockout lock from a machine? | Each authorised person removes only their own lock. An absent-owner exception requires contact attempts, Production Manager and Safety Officer authorization, an inspection, and a record. SAF-SOP-003, Rev 05, pp. 1–2, Removing Locks / Owner Absent. |
| What is the outer diameter tolerance for the BH-220 bearing housing? | 90.000 ± 0.050 mm using a digital caliper. QC-SOP-014, Rev 04, p. 2, Inspection Dimensions. |
| How often should spindle runout be checked, and who does it? | Monthly, by a maintenance technician. MNT-MAN-CNC-02, Rev 02, p. 1, Preventive Maintenance Schedule. |

### Five additional questions

| Question | Expected answer reference |
|---|---|
| For an incoming material lot containing 100 pieces, how many samples should the QC inspector inspect according to the latest procedure? | 100 is within the 91–500 band, so inspect 13 samples. QC-SOP-014, Rev 04, p. 1, Section 4 (Sampling Plan). |
| Can the inspector accept material if the supplier MTC is missing? | No. Put the lot on HOLD; do not inspect or accept until the mandatory MTC is received. QC-SOP-014, Rev 04, p. 2, Section 5. |
| What should happen if any sampled part has a critical defect? | Reject the complete lot and return it to the supplier; sorting is not allowed. QC-SOP-014, Rev 04, p. 1, Section 4. |
| What is the factory supervisor's salary? | Abstain: the supplied PDFs contain no salary information. |
| What is the alarm code for low coolant? | AL-412. Top up with coolant mixed to 6–8%. MNT-MAN-CNC-02, Rev 02, p. 2, Common Alarms. |

The same questions are listed in evaluation_questions.json. In the live app conversation, Gemini returned a grounded AL-104 answer citing MNT-MAN-CNC-02 Rev 02, Page 2. The user also shared the app's live 100-piece response: 13 samples, citing QC-SOP-014 Rev 04, Page 1. Those are two observed examples, not a claim that every answer in the tables was manually run through Gemini.

## Tests and manual checks

Run the automated suite:

       source .venv/bin/activate
       python -m unittest discover -s tests -v

The suite contains 11 tests, including a regression for the exact 100-piece question and a pass over all ten evaluation questions. Gemini calls are mocked in automated tests; the suite checks request construction, error handling, retrieval/source metadata, revision exclusion, and unsupported-question abstention. It does not measure live Gemini answer quality or consume API quota.

Manual checks recorded in the project conversation:
- A live AL-104 question returned a grounded answer with MNT-MAN-CNC-02 Rev 02, Page 2 citation.
- The 100-piece query returned 13 and QC-SOP-014 Rev 04, Page 1 (reported by the user).
- On Nov 10, 2026, the user reports completing the phone demonstration and recording it. The video is not stored in this project directory.
- Docker build/Compose startup remains unverified in this environment due Docker socket permissions.

## Same-Wi-Fi phone demo

1. Start the app locally or with Compose using the commands above.
2. On the Mac, get the current Wi-Fi IPv4 address immediately before the demo. Try ipconfig getifaddr en0; if it fails, inspect the active Wi-Fi interface with ifconfig en0 and use the inet address.
3. Connect the phone to the same Wi-Fi (not guest Wi-Fi). Disable a VPN on either device if it prevents local connections; avoid Wi-Fi client isolation.
4. If macOS requests it, allow incoming connections for Python/Uvicorn or Docker Desktop.
5. On the phone, browse to http://MAC_WIFI_IP:8000, replacing MAC_WIFI_IP with the current address. Do not reuse an old address; it may change.
6. Ask the AL-104 and BH-220 questions. Make sure the answer text and source document/revision/page are legible. Also show the unsupported salary question abstaining.

**Phone demo status:** The user reports that the app was successfully opened on their phone and recorded on November 10, 2026. No fixed IP is documented because the Mac's Wi-Fi address is dynamic. The recording itself was not found in the project folder; add its share link only if the assignment requires one and after checking sharing access.

### Suggested 2–3 minute recording sequence

- 0:00–0:20 — introduce the supervisor/use case and indexed documents
- 0:20–0:55 — AL-104 answer and manual source
- 0:55–1:25 — BH-220 tolerance and QC Rev 04 source
- 1:25–1:50 — unsupported salary question and abstention
- 1:50–2:25 — show the same app on the phone over Wi-Fi and ask a question
- 2:25–2:45 — mention the revision-aware improvement and table retrieval regression

## Limitations and next improvements

- Feature hashing is lightweight but is not semantic embedding; compare it against a pretrained model using a retrieval evaluation set before upgrading.
- The index is rebuilt in memory; a persistent vector store is unnecessary for four small source PDFs but would help with larger or frequently updated libraries.
- PDF text extraction may not represent every scanned or complex document; add OCR and inspect extraction quality when new source layouts appear.
- No user research has been conducted. Validate the assumptions, acceptable response time, safety escalation language, and phone usability with a real supervisor.
- Run and verify the Docker setup locally, and retain the Docker health status in the demo notes.

## Repository map

- app/main.py — ingestion, chunking, metadata, retrieval, revision handling, Gemini call, API
- app/static/ — mobile-friendly HTML, CSS, and JavaScript
- documents/ — the five supplied PDFs
- evaluation_questions.json — five supplied and five additional questions
- tests/test_rag.py — automated RAG/API checks
- Dockerfile, compose.yaml, .dockerignore — container setup and secret/build-context exclusions
- THINKING.md — user profile, journey drafts, AI challenge, improvement, reflection prompts
