# Deploying v2 to Azure App Service

v2 runs on the App Service v1 already uses. It needs no new Azure resources
and keeps v1's startup command. v1's data stays untouched on `/home`, so going
back to v1 is one redeploy.

## How it fits the App Service v1 set up

| What | v1 | v2 |
|---|---|---|
| Startup command | `uvicorn server:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips "*"` | The same. `server.py` hands it v2's app |
| Build on deploy | `SCM_DO_BUILD_DURING_DEPLOYMENT=true` installs `requirements.txt` | The same. v2's `requirements.txt` applies `constraints.txt` itself, so Azure installs the pinned versions |
| Live database | Container's own disk, `/tmp/xbrl-live` | Container's own disk, `/tmp/xbrl-v2-live` |
| Database copies | `<XBRL_OUTPUT_DIR>/db-copies` | `<XBRL_OUTPUT_DIR>/v2-db-copies`, its own folder and its own `owner.json` |
| Files (uploads, transcripts, logs) | `XBRL_OUTPUT_DIR=/home/data` | `XBRL_OUTPUT_DIR=/home/data-v2` (step 1) |
| Package | `scripts\deploy_azure.bat` | `scripts\deploy_azure.bat` (v2's own) |

Why it is built this way. These reasons come from v1, which found them the hard way:

- **The live database is never on `/home`.** `/home` is a network drive that
  cannot hold the locks SQLite needs. On 11 November 2026, v1's new and old
  containers both opened one file there during a deploy, and the app would not
  start. So the live file sits on the container's own disk. A copy is saved to
  `/home` every minute when something changed, soon after each job ends, and
  when Azure stops the app. A new container restores the newest good copy.
- **v2 keeps its own copies folder.** `owner.json` names the one container
  that may save. If v2 shared v1's folder, it would take that file over, and v1
  would stop saving after a rollback.
- **One process.** Never add `--workers`. The job worker, the login lockout
  and the copy saver all assume one process.
- **The lockout reads the address Azure's front end saw.** That is the last
  entry in the `X-Forwarded-For` header, without its port. The first entry,
  which uvicorn's `--proxy-headers` uses, is whatever the sender wrote. A
  person could change it on every guess and never be locked out.
- **Deploys go from the Windows laptop, not GitHub.** Deploying from GitHub
  would put enterprise Azure credentials in a personal repository.
- **The package lists what goes in.** v1 copied everything and left out
  folders by name. v2 adds only `app/`, `templates/`, `server.py`, the two
  requirement files and the built browser app. A new private folder can
  never reach Azure.
- **Accepted losses**, as for v1:
  - A job that is mid-way during a restart is marked for retry.
  - Changes the old container makes in the minute of changeover are lost.
  - A crash loses at most a minute.

What does not carry over: v1's runs, accounts and settings. v2 starts with
an empty database and the Settings page's defaults.

## First v2 deploy

### 0. Before you start

- The commit to deploy has passed `venv/bin/python -m pytest tests/ -q` and the
  web build and tests on the Mac.
- Pick a quiet time: a v1 run that is mid-way during the switch is lost.
- Portal: Overview > **Stop**. Changing a setting restarts the app that is
  already there. With v1 still deployed, it would restart on v2's empty
  folder, and anything people did in it would be lost.

### 1. Change the App settings (portal: Web app > Settings > Environment variables)

| Setting | Value | Why |
|---|---|---|
| `XBRL_OUTPUT_DIR` | `/home/data-v2` | v1's files stay as they are in `/home/data` |
| `BOOTSTRAP_ADMIN_EMAIL` | your email | v2 starts with no accounts |
| `BOOTSTRAP_ADMIN_PASSWORD` | a temporary password, 12+ characters | Deleted again in step 4 |

Leave these as v1 has them:

- `SESSION_SECRET`
- `PYTHONUTF8=1`
- `SCM_DO_BUILD_DURING_DEPLOYMENT=true`
- `WEBSITES_ENABLE_APP_SERVICE_STORAGE=true`
- `WEBSITES_CONTAINER_STOP_TIME_LIMIT=120`
- the model keys

v2 reads the same key names: `OPENAI_API_KEY` and `ANTHROPIC_API_KEY`, or
`LLM_PROXY_URL` with `LLM_PROXY_API_KEY` for the gateway. Never set
`AUTH_MODE`. Leave the startup command alone. Click **Apply**.

### 2. Deploy from the Windows laptop, then start the app

```
cd <your xbrl-agent-v2 folder>
git pull
set AZ_RESOURCE_GROUP=<your resource group>
set AZ_APP_NAME=<your web app name>
scripts\deploy_azure.bat
```

If the Azure command-line tool is missing, the script prints the Cloud Shell
steps instead: upload the zip it built, then run the `az webapp deploy` line it
shows.

Portal: Overview > **Start**.

### 3. Check it and sign in

1. Open `https://<your-site>/api/health`. `commit` names the commit the script
   printed, and `database_copy` shows `"saving": true`.
2. Open the site and sign in with the email and temporary password from step 1.
3. Change the password. On the Settings page, choose the models.

### 4. Remove the first-start settings

Delete `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`, then click
**Apply**. The app restarts and restores its saved copy. Sign in again with your
new password: if that works, the copies work. Then add the other people.

### 5. Check it holds

1. Run one document to the end.
2. Portal: Overview > **Restart**. Wait two minutes.
3. The run is still there and its downloads open.
4. `/api/health` shows a recent `last_saved_at` and `"stale": false`.

## Later deploys

Steps 0 and 2 only.

## Going back to v1

1. Portal: Overview > **Stop**, for the same reason as in step 0.
2. Set `XBRL_OUTPUT_DIR` back to `/home/data`. Click **Apply**.
3. From v1's folder on the laptop, run v1's `scripts\deploy_azure.bat`.
4. Portal: Overview > **Start**.

v1 restores its own copies from `/home/data/db-copies`, which v2 never touched.
v2's data stays in `/home/data-v2` for the next try.

## Not yet confirmed on Azure

Everything here was tested on the Mac in a setup that mimics Azure:

- the exact startup command;
- a pretend `/home`;
- a stop, then a fresh container restoring the copy;
- the package installed into an empty folder with its own Python environment.

Only a real deploy confirms the rest:

- Azure's own build;
- the company proxy for `az`;
- the start time on Azure;
- that Azure's front end is the last entry in `X-Forwarded-For`. If another
  proxy (such as Front Door) ever sits in front, the lockout would count
  that proxy's address instead. A cold start took under two seconds on the
Mac, well inside Azure's 230-second start limit.
