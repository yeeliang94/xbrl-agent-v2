# XBRL Agent v2

An AI assistant that turns a Malaysian company's audited financial statements
(a PDF) into a filled XBRL workbook for SSM's mTool, ready for a person to
check and file.

Preparing an XBRL filing by hand means retyping every figure and note from
the audited accounts into a large template. This app does the first pass:

1. **Read.** It finds each statement in the PDF and works out the standard
   (MFRS or MPERS), the level (company or group), the unit and each
   statement's layout.
2. **Fill.** One AI agent per statement copies every figure into the
   matching template line, citing the page it came from. A notes agent places
   the notes and accounting policies.
3. **Check.** Totals, cross-statement links and last year's figures are
   checked. Anything that doesn't tie goes into a review queue. A total is
   never forced to balance, and a missing line is never treated as zero.
4. **Review.** A person works through the queue side by side with the PDF
   page. They can accept or correct each figure, or ask the agent to fix it.
   Every change is kept in a history.
5. **Download.** The filled mTool workbook, plus reports on what was filled
   and what still needs a person.

## Built with

- **Server:** Python 3.12, FastAPI, PydanticAI, SQLite.
- **Browser app:** React, TypeScript, Vite.
- **Models:** OpenAI and Anthropic, called directly or through a company AI
  gateway.

## Run it

You need Python 3.12 and Node.js.

```bash
cp .env.example .env      # add your model API key
./start.sh                # Mac or Linux
```

On Windows, run `start.bat`. Either script sets up the Python environment,
installs the packages, builds the browser app and starts it at
`http://localhost:8100`.

## Tests

```bash
venv/bin/python -m pytest tests/ -q
cd web && npm test
```

Tests that call a real model are marked `live` and are left out by default.
The test documents are real filings and are not part of this repository, so
the live tests skip any document they cannot find.

## Deploying

`scripts/deploy_azure.bat` packages the app and sends it to Azure App
Service. `docs/azure-deploy.md` explains the setup.

## Find your way around

- `app/`: the server. `web/`: the browser app. `tests/`: server tests.
- `templates/`: SSM's published XBRL taxonomy and mTool templates.
- `docs/backend-plan.md`: the design and the build order.
- `docs/build-log.md`: what each step delivered and how it was checked.
- `docs/api-contract.md`: what the browser and the server say to each other.
- `prototypes/`: clickable screen designs. Open any of them in a browser.
- `AGENTS.md`: the rules for AI coding agents working on this repository.

## Status

Work in progress. Steps 0 to 10 of 12 are built and tested on a Mac. They
cover reading, every statement, notes, review, MPERS, reports and the mTool
fill. `docs/build-log.md` has the detail.
