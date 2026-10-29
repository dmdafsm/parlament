# ADR 0006: plain-language bill summaries from a local open-weight model

Status: accepted (maintainer chose a local model and RoGemma3-4B on 2026-10-28, and Tesseract for scans on 2026-10-29). Date: 2026-10-28, updated 2026-10-29. Related tasks: P6.

## Context

Bill titles are legal references ("pentru completarea art.291 din Legea nr.227/2015"), not explanations. Each bill has an explanatory memorandum (expunerea de motive), a PDF in which the initiator states the problem and the proposed change. A summary needs a language model. The maintainer did not want a paid API and asked for an open-weight model small enough to run locally. OpenLLM-Ro publishes Romanian-tuned models on Hugging Face.

Observations from a sample of 8 bills (2026-10-28):
- About 1,050 memoranda are on senat.ro, a third of them scans with an OCR text layer ('baz5', 'Schimbdri preconlzate').
- RoGemma3-4B-Instruct (4-bit MLX, 2.1 GB, ~2.4 s per bill on an M5 Pro) summarised the opening of the memorandum as if it were the proposal (2 of 8 inverted). It also speculated about effects.
- Feeding the opening (context) and the section that states the change separately, matched loosely to survive OCR, and asking for "Proiectul propune …" without speculation, gave 8 correct summaries of 8.

## Decision

- `parlament ingest memoranda` (`ingest/bill_texts.py`) stores the beginning of each memorandum's text in `bill_texts`, preferring the senat.ro copy. Scans without a text layer are stored with NULL and get no summary.
- `parlament ingest ocr` reads the memoranda stored without text with Tesseract (Romanian data), from the PDFs kept under `data/raw/`. The 295 Chamber-only memoranda on cdep.ro are printer scans with no text layer. Rendering uses pypdfium2, an optional `ocr` extra (`uv run --extra ocr ...`); like the summaries it runs only on the maintainer's machine, so the containers need neither.
- `parlament summarize` (`summaries.py`) calls an OpenAI-compatible endpoint (`PARLAMENT_LLM_URL`, default `http://127.0.0.1:8091/v1`, e.g. `mlx_lm.server`) and writes `bill_summaries` with the model label and source PDF. It runs by hand on the maintainer's machine, not in the scheduler or the containers. No text leaves the machine.
- Model: OpenLLM-Ro/RoGemma3-4B-Instruct (CC BY-NC 4.0, non-commercial use, attribution), converted locally to MLX 4-bit. The published checkpoint has an extra `lm_head.weight` despite tied embeddings; it is dropped before `mlx_lm.convert`.
- The bill page shows the summary in a separate box, labelled as generated, with the model, its license, the source memorandum and a link to the methodology. The summary presents the initiator's view.

## Alternatives and consequences

- A hosted API (Claude) would be more accurate but costs per bill and sends texts to a third party; the maintainer declined it.
- RoLlama3.1-8B-DPO (16 GB before conversion) would likely be more robust; it can replace the model by changing `PARLAMENT_LLM_LABEL` and re-running `summarize`. Summaries are keyed by model label, so a new model regenerates them all.
- CC BY-NC 4.0 rules out commercial use of the summaries; the site is non-commercial. A commercial reuse of the open data must leave them out.
- The model still speculated in about 4% of 1,017 summaries despite the prompt; `tidy` drops sentences with 'ar putea' / 'probabil'.
- Tesseract on the cdep.ro scans (about 7 s per memorandum on an M5 Pro) gave clean text on a sample of 3; a scan it cannot read stays NULL and gets no summary.
- Errors remain possible, especially on poor OCR text. The label, the source link and the methodology section say so.

## Verification

- `uv run pytest tests/test_summaries.py tests/test_web.py`: selection of memoranda, NULL for scans, OCR filling scans (with a stub reader), excerpt matching on OCR text, a summary written through a mock endpoint and shown on the bill page.
- Manual: 8 bills summarised with the local model and checked against their memoranda.
