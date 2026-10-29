# Hermes v0.21.5 → v0.22.5 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the `adm1neca/hermes-agent` fork and all deployed agents (default, pilot, forge/coding, research, reviewer) from v0.21.5 (`v2026.9.24`) to **v0.22.5** (stable, 2026-10-22), with zero memory, session or wiki-RAG loss.

**Architecture:** Four phases. **Phase A (Tasks 1–3):** a pre-flight gate that fetches upstream and trial-merges, then **stops for user review**; a safety net; and defusing the new runtime hazards (session auto-prune, retired `session_reset`) before any v0.22 code runs. **Phase B (Tasks 4–6):** a real 3-way merge of the `v0.22.5` tag, take-theirs-then-reapply conflict resolution, and re-homing the patches the second god-file split moved. **Phase C (Tasks 7–10):** image rebuild (Python 3.14 + `hermes pm`), the Honcho-to-catalog-plugin migration, redeploy, and the host-native update. **Phase D (Task 11):** end-to-end verification and memory.

**Tech Stack:** Git (3-way merge), Docker + Compose (s6-overlay image, Debian 13), Python 3.14 / uv / `hermes pm`, Git Bash + PowerShell on Windows 10, 16 GB RAM.

**Spec:** Upstream release notes for v0.21.6, v0.21.7, v0.22.0 ("⚠️ Upgrade notes" section) and v0.22.5 (`gh release view <tag> -R NousResearch/hermes-agent`), plus the previous plan `docs/superpowers/plans/2026-09-25-hermes-v0215-upgrade.md` (read its **Execution outcome** section first) and memory `hermes-v0215-upgrade.md`.

**Model routing (user preference: cheaper models where they suffice):**

| Task | Suggested executor | Why |
|---|---|---|
| 2, 7, 10 | Haiku subagent | Mechanical: backups, builds, `hermes update`, with exact commands and expected output |
| 1, 3, 8, 9 | Sonnet subagent | Needs judgement reading logs, diffs and release notes, but no code authoring |
| 4, 5, 6 | Opus (main session) | Conflict resolution and re-homing patches into refactored modules |
| 11 | Sonnet for checks; main session writes memory | |

---

## Pre-flight findings (verified 2026-10-29 against live state)

- **Local:** `main` = `origin/main` at `b2b9bca7a7`, merge base for the last upgrade = tag `v2026.9.24`. Tree is clean except two untracked `compose.hermes.local.yml.bak-*` files.
- **Upstream stable:** `v0.22.5` (2026-10-22). Window: v0.21.6 (~8.9k commits), v0.21.7 (~740), v0.22.0, v0.22.1–.5 (v0.22.5 alone: 231 commits). **Assume more than 10k commits.**
- **The first `git fetch upstream` died** (`fatal: fetch-pack: invalid index-pack output`) because Claude Code reaped it for low memory. It left `.git/objects/pack/tmp_pack_Ngle7J` (296 MB). Task 1 cleans that up and re-fetches **detached**.
- **Local patch set vs `v2026.9.24`** (38 files): **M** `.gitignore`, `Dockerfile`, `agent/agent_init.py`, `agent/turn_usage.py`, `docker/stage2-hook.sh`, `gateway/run.py`, `hermes_cli/profiles.py`, `plugins/platforms/telegram/adapter.py`, `web/package.json`; **A** `agents/*-config.yaml` (4), `docker/Dockerfile.sandbox*` (2), `mission_control_reporter.py`, `optional-skills/albert-heijn/**`, `skills/devops/telegram-callback-integration/**`, `upgrade-v016-plan.md`, `docs/superpowers/plans/**`.
- **All 5 live configs are at `_config_version: 46`**, `memory.provider: honcho`.
- **`sessions.auto_prune`:** explicitly `false` in default, coding, research and reviewer. **Pilot has no `sessions:` block**, so under v0.22's new default (`auto_prune` on, 90 days) pilot's ended sessions older than 90 days would be **deleted at first boot**. Task 3 pins it.
- **`session_reset: {mode: both, idle_minutes: 1440, at_hour: 4}`** in default and pilot. v0.22 retires idle/daily resets: the setting only logs a warning, and chats stop auto-resetting.
- **Dockerfile:307** has `--extra honcho`. v0.22 moved Honcho to a **catalog plugin**, so that extra very likely no longer exists, and `uv sync --frozen` would fail. This is the same trap Hindsight caused in v0.21.
- **Dockerfile:43** uses `uv:0.11.6-python3.13-trixie`. v0.22 makes **Python 3.14** the runtime. If the image moves to 3.14, the wiki-RAG `_vendor` dir in the `rag-data` volume (built for 3.13) **will break**. Re-vendor in Task 9.
- **No Hermes container publishes ports** (`docker ps` shows none for `hermes`/`hermes-dashboard`). The v0.21.6 dashboard-auth CVEs are lower urgency than they first looked. Confirm in Task 1 whether the dashboard uses `network_mode: host`.
- **`E:` is 94% full (48 GB free).** The offline backup plus the image build need space. Task 2 checks it first.
- **Upstream still treats one multiplexing gateway per container as the topology.** v0.22 calls `gateway.standalone` a "temporary opt-out". We don't use it (removed 2026-09-25), so no change. `~/.hermes/profiles/` must still contain only `pilot`.

### Task 1 findings (2026-10-29)

- **Fetch:** v0.22.5 tag fetched OK on first try (stale tmp_pack removed first). Upstream push is disabled; `git push --dry-run upstream main` fails as required.
- **Merge base:** `git merge-base HEAD v0.22.5` = `f97608f178d1ffeca59860195ab7da295f7c8e5f` = `v2026.9.24^{commit}` (match, real merge base).
- **Scale:** 16231 commits (v2026.9.24..v0.22.5); `13049 files changed, 1278488 insertions(+), 338380 deletions(-)`. Rename detection skipped in plain diff (needs diff.renameLimit >= 6157); merge-tree run with renameLimit=20000.
- **Trial merge (merge-tree, tree 65dc3407...) - 3 conflicts, all in our M list:** `Dockerfile`, `gateway/run.py`, `plugins/platforms/telegram/adapter.py`. Auto-merged cleanly: `.gitignore`, `agent/agent_init.py`, `agent/turn_usage.py`, `docker/stage2-hook.sh`, `hermes_cli/profiles.py`, `web/package.json`. Log: backups\hermes-pre-v0225-2026-10-29\logs\merge-tree.txt.
- **honcho extra: NO.** v0.22.5 `pyproject.toml` has no `honcho = [...]` extra (only the comment at line 516 "matrix, slack, honcho, voice"); our fork has `honcho = ["honcho-ai==2.2.0"]` at line 258. Our Dockerfile adds `--extra honcho`; upstream's build_env line (Dockerfile:289-293) ends `--extra azure-identity --extra matrix --extra google-chat`. Honcho SDK is now lazy-installed (`ensure("memory.honcho")`); in-tree `hermes_cli/profiles_honcho.py` and plugin-catalog `honcho.yaml` exist. The Dockerfile conflict resolution must NOT re-add `--extra honcho` against an extra that no longer exists (uv would fail) - decide: bake honcho-ai another way or rely on lazy install.
- **Python / Dockerfile:** NO `uv_source` stage and no `ghcr.io/astral-sh/uv:...-python3.13` FROM any more (only a comment at line 183 mentioning it). Bases are `debian:trixie-20261020@sha256:4c25...` (sqlite_build, runtime_base). uv/python/node/ffmpeg are provisioned by `pm` from `pm/lock.json`; python = **cpython 3.14.9** (python-build-standalone 20261021), `requires-python = ">=3.11,<3.15"`. **Python moves 3.13 -> 3.14: wiki-RAG needs re-vendoring (Task 9 Step 6).**
- **`hermes pm`:** Dockerfile has no literal `hermes pm`; it uses `python3 -m pm.cli install` / `python3 -m pm.build_env` (pm/ dir copied in).
- **Config version:** `_config_version` = **51** (`hermes_cli/config_defaults.py:2731`; moved out of config.py).
- **Hook point homes at v0.22.5:**
  - `session_cost_source = ` (MC usage hook): `agent/turn_usage.py:252` (ours today line 244); also `agent/codex_runtime.py:209`.
  - `_publish_session_id`: `agent/agent_init.py:1166` def, called at 1189 (ours 1127/1150).
  - `_handle_callback_query`: `plugins/platforms/telegram/adapter.py:4710`. Dispatch is now two table loops: picker prefixes (mp:/cp:...) then `("gt:", gmail_triage), ("ea:"), ("sc:"), ("cl:"), ("update_prompt:")` at ~4728-4731. We have our own `gt:` gmail-triage entry (and no "paper-digest" string exists upstream); it is a tuple in the second loop - adapter.py is a conflict file. `update_prompt:` button at 4207, handler 4904.
  - `_get_profiles_root`: `hermes_cli/profiles.py:283`; upstream is `_get_default_hermes_home() / "profiles"` (via `get_default_hermes_root()`), NOT anchored at Path.home()/.hermes/profiles. Our local fallback patch (Path.home()/.hermes/profiles when computed absent) auto-merged without conflict - verify post-merge it survives.
  - `except PermissionError` replace path: moved out of gateway/run.py (0 hits there) into `gateway/run_bootstrap.py:90-95` (`_start_gateway_replace_existing_instance`, def at line 30). Upstream order is still `except ProcessLookupError: pass` then `except (PermissionError, OSError):` -> "Permission denied... Cannot replace" return False; it does NOT catch OSError with ProcessLookupError, so our Windows invalid-PID patch is NOT upstreamed. gateway/run.py conflict: our hunk (run.py:5175-5182) targets code that upstream moved, so the patch must be re-applied to run_bootstrap.py:93 (and probably the SIGKILL path at 105) and run.py's side taken as upstream.
  - `start_gateway` itself: `gateway/run.py:5089` is now a thin wrapper calling `gateway.run_bootstrap.start_gateway` (line 728).
- **docker-compose.yml (upstream):** dashboard service `network_mode: host` (line 67), command `dashboard --host 127.0.0.1 --no-open`; gateway also `network_mode: host` (line 35).
- **Surprising:** (1) 16k commits / 13k files. (2) Python 3.14 + pm-provisioned toolchain replaces the uv image. (3) honcho extra removed. (4) the PermissionError patch target moved files and upstream did not fix the OSError case. (5) Untracked `compose.hermes.local.yml.bak-*` files in the repo root (pre-existing, not touched).

---

## Decisions (defaults chosen; override before executing)

1. **Target:** the **`v0.22.5` tag**, not `upstream/main`. Source installs now follow tagged stable releases. A tag also gives a reproducible merge base for the next upgrade.
2. **Session auto-prune:** **Default: keep everything.** Set `sessions.auto_prune: false` in pilot too, so all five match. Alternative: let v0.22 prune ended sessions older than 90 days (it never touches pinned or open ones).
3. **`session_reset`:** **Default: delete the `session_reset` block** from default and pilot. It is now inert and only logs a warning; `/new` and `/reset` remain. Alternative: leave it and live with the warning.
4. **Honcho as a plugin:** **Default: let upstream's automatic migration install the Honcho catalog plugin**, and remove `--extra honcho` from the Dockerfile **only if** Task 1 proves the extra is gone. Verify data with the per-row hash method from the Honcho v3.2.1 upgrade (no rows lost, same peer/workspace ids).
5. **New Telegram default `extra.drop_pending_on_cold_boot`:** the notes call `false` the opt-in that keeps messages sent while offline. **Default: leave it at upstream's default.** We have never relied on catch-up delivery.
6. **Tool renames (`todo`→`todo_list`, `cronjob`→`cronjob_manage`, `process`→`process_manage`):** the old names still work. **Default: don't touch skills or crons now.** Task 11 greps for the old names and reports what it finds.

---

## Global Constraints

- **Fork:** `origin` = `adm1neca/hermes-agent`. `upstream` is fetch-only; its push URL is `DISABLED_no_push_to_upstream`. `git push --dry-run upstream main` **must fail** before Task 4. Push only `origin main` ([[hermes-fork-push-policy]]).
- **Dev repo:** `E:\GITHUB\projects\hermes-agent`. **Host-native install:** `C:\Users\Plamen\.hermes\hermes-agent` (shallow clone of the fork).
- **Source tag** `v2026.9.24` (v0.21.5) → **target tag** `v0.22.5`. **Pre-upgrade HEAD:** `b2b9bca7a7`. **Required merge base:** whatever Task 1 Step 3 prints must equal `git rev-parse v2026.9.24^{commit}`. If it differs, STOP: a squash merge has recurred ([[git-squash-merge-gotcha]]).
- **Memory: run heavy jobs ONE AT A TIME** ([[feedback-windows-heavy-jobs-sequential]]). Launch `git fetch`, `git merge`, `docker compose build`, the test run and `hermes update` as detached jobs that write to a log, and watch them with Monitor:
  `powershell -c "Start-Process cmd -ArgumentList '/c','<cmd> > E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\<name>.log 2>&1' -WindowStyle Hidden"`
  Give the user the size or ETA up front, plus short progress updates ([[feedback-progress-during-long-waits]]).
- **Graceful stop only:** `docker compose -f docker-compose.yml -f compose.hermes.local.yml stop -t 60`. First verify that compose still carries `stop_grace_period: 60s` and `S6_SERVICES_GRACETIME`/`S6_KILL_GRACETIME: "30000"` ([[feedback-hermes-graceful-stop]]). An unclean exit costs a ~20-min `state.db` integrity check.
- **Never** run `docker compose down -v` (it would destroy the `hermes-agent_rag-data` volume; [[wiki-rag-system]]). **Never** mount `docker.sock` into the `gateway` (`hermes`) service.
- Windows: `MSYS_NO_PATHCONV=1` for `docker exec`/`docker run -v` with container paths. `docker/*.sh` must stay LF. Exclude `node_modules`/`.git`/`dist` from greps. Use Windows paths for files Windows Python reads (not Git Bash `/tmp`).
- **Deviation rule:** if any live result differs from this plan by an order of magnitude (conflict count, test failures, migration changes), STOP and find the root cause before continuing ([[feedback-plan-deviation-handling]]).
- Commit after every repo-changing task. Never amend. `.gitignore` excludes `docs/superpowers/*`, so add plan files with `git add -f`.

## Review Focus

Failure modes that no task's happy path exercises, most likely first. Each one has a check in the owning task.

1. **Honcho memory silently empty after the plugin move.** Agents answer, but with no recalled memory, because the plugin isn't installed in a container or points at a fresh workspace or peer. → Task 9 Step 5: a recall probe and a per-row hash diff, not just `honcho status`.
2. **Pilot sessions pruned at first boot.** Pilot has no `sessions.auto_prune` key. → Task 3 Step 2 pins it; Task 9 Step 4 compares session counts before and after.
3. **Wiki-RAG `_vendor` ABI break under Python 3.14.** Import errors, or a silent fallback to empty results. → Task 9 Step 6: a real `wiki-rag` query must return hits, and the Chroma count must equal the `chunks_fts` count.
4. **A duplicate Telegram poller** from a profile dir that reappeared or from v0.22's auto-fold of per-profile gateways. → Task 9 Step 3: check `getUpdates` conflicts in all four Hermes containers.
5. **Paper-digest buttons stop working** because the Telegram callback dispatch moved again. → Task 11 Step 2: a real button press.

---

## Task 1: Pre-flight gate (fetch, trial merge, inventory) — STOP for review at the end

**Executor:** Sonnet. **No source changes.**

- [ ] **Step 1: Clean up the dead fetch.** No git process may be running.

```bash
cd /e/GITHUB/projects/hermes-agent
tasklist | grep -i "git" || rm -f .git/objects/pack/tmp_pack_*
mkdir -p /e/GITHUB/backups/hermes-pre-v0225-2026-10-29/logs
```

- [ ] **Step 2: Fetch tags, detached.** Expect several hundred MB and 5–15 min. Tell the user before starting.

```bash
powershell -c "Start-Process cmd -ArgumentList '/c','cd /d E:\GITHUB\projects\hermes-agent && git fetch upstream tag v0.22.5 --no-tags > E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\fetch.log 2>&1 && echo FETCH_DONE >> E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\fetch.log' -WindowStyle Hidden"
```

Watch the log with Monitor until it shows `FETCH_DONE` or `fatal`. If it fails again with `index-pack`, retry once with `git -c pack.threads=1 -c core.packedGitLimit=256m fetch ...` to cut memory use.

- [ ] **Step 3: Merge base and scale**

```bash
git rev-parse v2026.9.24^{commit}
git merge-base HEAD v0.22.5            # MUST equal the line above
git rev-list --count v2026.9.24..v0.22.5
git diff --shortstat v2026.9.24 v0.22.5
git push --dry-run upstream main       # MUST fail
```

- [ ] **Step 4: Trial merge (no working-tree change)**

```bash
git -c merge.renameLimit=20000 merge-tree --write-tree --name-only HEAD v0.22.5 > /e/GITHUB/backups/hermes-pre-v0225-2026-10-29/logs/merge-tree.txt; echo exit=$?
sed -n '2,/^$/p' /e/GITHUB/backups/hermes-pre-v0225-2026-10-29/logs/merge-tree.txt
```

Expected: conflicts only in files from our **M** list (at most 9). Record the exact list; Task 4 asserts against it. An `A` file of ours that conflicts with an upstream deletion or rename is fine, but list it.

- [ ] **Step 5: Inventory what moved** (read-only, all at `v0.22.5`)

```bash
T=v0.22.5
git show $T:pyproject.toml | grep -n -A2 -E "^\[project.optional-dependencies\]|^honcho|^all ="   # does the 'honcho' extra still exist?
git show $T:Dockerfile | grep -n -E "^FROM|uv sync|python3\.[0-9]+|hermes pm"                       # base images, Python minor, sync line
git ls-tree -r --name-only $T | grep -i honcho | head -20                                        # in-tree or gone?
git ls-tree -r --name-only $T | grep -E "^agent/turn_usage|^agent/agent_init|^gateway/run(_.*)?\.py$|telegram/adapter" 
git grep -n "_publish_session_id\|session_cost_source = " $T -- agent/ | head
git grep -n "def _handle_callback_query\|update_prompt:" $T -- plugins/platforms/telegram/ gateway/ | head
git grep -n "def _get_profiles_root" $T -- hermes_cli/ | head
git grep -n "except PermissionError" $T -- gateway/run*.py | head
git show $T:docker-compose.yml | grep -n -E "network_mode|ports|dashboard" | head
git show $T:hermes_cli/config.py 2>/dev/null | grep -n "_config_version" | head -3 || git grep -n "\"_config_version\":" $T -- hermes_cli/ | head -3
```

- [ ] **Step 6: Write the findings into this plan** (a "Task 1 findings" section under Pre-flight): commit count, conflict list, honcho extra yes/no, Python minor in the image, config version, and the new homes for the 5 patch hook points. **STOP and show the user.** Phase B starts only after their go-ahead. If Python moved to 3.14, say up front that wiki-RAG needs re-vendoring (Task 9 Step 6).

---

## Task 2: Safety net

**Executor:** Haiku. **No source changes.**

- [ ] **Step 1: Disk space.** Need at least 25 GB free on `E:` after the backup.

```bash
df -h /e | tail -1
du -sh /c/Users/Plamen/.hermes /e/GITHUB/projects/hermes-data 2>/dev/null
du -sh /e/GITHUB/backups/* | sort -h
```

If free space minus the backup size is under 25 GB, **ask the user** which old `E:\GITHUB\backups\hermes-pre-v01*` dirs may be deleted. Never delete them unasked.

- [ ] **Step 2: Rollback tag and branch**

```bash
cd /e/GITHUB/projects/hermes-agent
git tag pre-v0.22.5-snapshot-2026-10-29 && git branch pre-v0.22.5-snapshot
git push origin pre-v0.22.5-snapshot-2026-10-29 pre-v0.22.5-snapshot
```

- [ ] **Step 3: Baseline effective state** (inputs to Tasks 8, 9 and 11)

```bash
B=/e/GITHUB/backups/hermes-pre-v0225-2026-10-29/baseline; mkdir -p $B
cp /c/Users/Plamen/.hermes/config.yaml $B/raw-default.yaml; cp /c/Users/Plamen/.hermes/profiles/pilot/config.yaml $B/raw-pilot.yaml
for a in coding research reviewer; do cp /e/GITHUB/projects/hermes-data/$a/config.yaml $B/container-$a.yaml; done
ls /c/Users/Plamen/.hermes/profiles/ > $B/profiles-dir.txt        # expect: pilot
export MSYS_NO_PATHCONV=1
docker exec hermes ps -eo pid,args | grep "gateway run" | grep -v grep > $B/gateways-before.txt
for c in hermes hermes-agent-forge-1 hermes-agent-research-1 hermes-agent-reviewer-1; do
  echo "== $c"; docker exec $c hermes sessions list --limit 1 2>&1 | head -3
  docker exec $c sh -c 'for d in /opt/data/state.db /opt/data/profiles/*/state.db; do [ -f "$d" ] && echo "$d $(python3 -c "import sqlite3,sys;print(sqlite3.connect(sys.argv[1]).execute(\"select count(*) from sessions\").fetchone()[0])" "$d")"; done'
done > $B/session-counts.txt 2>&1
docker exec hermes-agent-research-1 hermes plugins list > $B/plugins-research.txt 2>&1
docker exec hermes hermes cron list > $B/cron-default.txt 2>&1; docker exec hermes hermes -p pilot cron list > $B/cron-pilot.txt 2>&1
```

If the `sessions` table name differs, use `.tables` and adjust. The goal is a row count per `state.db`.

- [ ] **Step 4: Honcho baseline.** Use the per-row hash diff method from [[honcho-server-upgrade-v321]]. Dump `(table, id, sha1(row))` for the `peers`, `sessions`, `messages`, `documents` and `collections` tables from `honcho-database-1` into `$B/honcho-rows-before.tsv`. The server itself is **not** being upgraded; this only guards against the client-side plugin migration writing to a different workspace.

- [ ] **Step 5: Verify graceful-stop settings, then do the offline backup**

```bash
grep -n -E "stop_grace_period|S6_SERVICES_GRACETIME|S6_KILL_GRACETIME" compose.hermes.local.yml   # expect 4 services × 3 lines
```

```powershell
cd E:\GITHUB\projects\hermes-agent
docker compose -f docker-compose.yml -f compose.hermes.local.yml stop -t 60
robocopy "C:\Users\Plamen\.hermes" "E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\.hermes" /E /R:1 /W:1 /XD hermes-agent node_modules
robocopy "E:\GITHUB\projects\hermes-data" "E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\hermes-data" /E /R:1 /W:1
docker run --rm -v hermes-agent_rag-data:/v -v E:/GITHUB/backups/hermes-pre-v0225-2026-10-29:/b alpine tar czf /b/rag-data.tgz -C /v .
```

Robocopy exit codes 0–7 mean success; expect `FAILED: 0` on both. **Downtime starts here.** If Phase B will take more than ~1 h, restart now with `... up -d` (safe, nothing has changed yet) and repeat only the `stop -t 60` step just before Task 9.

---

## Task 3: Defuse runtime hazards (host-side, before any v0.22 code runs)

**Executor:** Sonnet. **Files:** runtime configs only (not the repo). These edits are inert on v0.21.5.

- [ ] **Step 1: Profile dir check**

```bash
ls /c/Users/Plamen/.hermes/profiles/     # MUST be exactly: pilot
```

Any other dir gets multiplexed and could poll a live bot token. Move it to `E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\retired-profiles\` after telling the user.

- [ ] **Step 2: Pin `sessions.auto_prune: false` in pilot** (Decision 2). Add a top-level block to `C:\Users\Plamen\.hermes\profiles\pilot\config.yaml`:

```yaml
sessions:
  auto_prune: false
```

- [ ] **Step 3: Remove `session_reset`** (Decision 3) from `C:\Users\Plamen\.hermes\config.yaml` and the pilot config: the whole `session_reset:` mapping (`mode: both`, `idle_minutes: 1440`, `at_hour: 4`).

- [ ] **Step 4: Verify**

```bash
for f in /c/Users/Plamen/.hermes/config.yaml /c/Users/Plamen/.hermes/profiles/pilot/config.yaml /e/GITHUB/projects/hermes-data/{coding,research,reviewer}/config.yaml; do
python - "$f" <<'EOF'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1], encoding="utf-8"))
ap = (c.get("sessions") or {}).get("auto_prune")
assert ap is False, f"{sys.argv[1]}: auto_prune={ap!r}"
assert "session_reset" not in c, f"{sys.argv[1]}: session_reset still present"
print("OK", sys.argv[1])
EOF
done
```

Expected: five `OK` lines.

---

## Task 4: Merge the `v0.22.5` tag

**Executor:** Opus.

- [ ] **Step 1: Start the merge detached**

```bash
powershell -c "Start-Process cmd -ArgumentList '/c','cd /d E:\GITHUB\projects\hermes-agent && git -c merge.renameLimit=20000 merge v0.22.5 --no-commit > E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\merge.log 2>&1 & echo MERGE_EXIT=%ERRORLEVEL% >> E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\merge.log' -WindowStyle Hidden"
```

Wait for `MERGE_EXIT=`. If a stale `.git/index.lock` remains and no git process is running, remove it.

- [ ] **Step 2: Assert the conflict set equals Task 1 Step 4**

```bash
git diff --name-only --diff-filter=U | sort
```

If it's materially different from the recorded list, STOP (deviation rule).

- [ ] **Step 3: Resolve each conflict.** Take upstream's whole file, then re-apply our patch at its new home (Task 5). This worked well on v0.21.5.

| File | Resolution |
|---|---|
| `Dockerfile` | `git checkout --theirs Dockerfile`. If Task 1 showed a `honcho` extra still exists, append `--extra honcho` to upstream's `uv sync` line. If not, add nothing (Decision 4). Re-add our honcho comment only if the extra stays. |
| `hermes_cli/profiles.py` | `--theirs`, then re-apply snippet A to `_get_profiles_root()` (find it with `grep -rn "def _get_profiles_root" hermes_cli/`). AGENTS.md now says the root is `Path.home()/.hermes/profiles`. **If upstream already anchors it there, retire this patch** and say so. |
| `gateway/run.py` (or whichever `gateway/run_*.py` sibling now owns `start_gateway`'s replace path) | `--theirs`, then reorder: `except (ProcessLookupError, OSError): pass` before `except PermissionError: …`. Find it with `grep -rn "except PermissionError" gateway/run*.py`. **If upstream's order already avoids the Windows `PermissionError` (a subclass of `OSError`) being swallowed, retire the patch.** |
| `agent/agent_init.py` | `--theirs`; Task 5 Step 2 re-adds `MISSION_CONTROL_SESSION_ID`. |
| `agent/turn_usage.py` | `--theirs`; Task 5 Step 1 re-adds the MC usage hook. |
| `plugins/platforms/telegram/adapter.py` (or the sibling that now owns `_handle_callback_query`) | `--theirs`; Task 5 Step 3 re-homes the paper-digest callbacks. |
| `docker/stage2-hook.sh`, `web/package.json`, `.gitignore` | Hand-merge if they conflict. Keep the docker.sock group block and `chmod 666` fallback (stage2), the `sync-assets` fix (web), and our ignore lines. Confirm stage2 stays LF: `file docker/stage2-hook.sh`. |

Snippet A (`hermes_cli/profiles.py`):

```python
def _get_profiles_root() -> Path:
    """Named-profiles root, anchored to the hermes root (NOT the current HERMES_HOME, which
    may itself be a profile) so ``coder profile list`` sees all profiles.

    Local patch: on Windows installs predating the %LOCALAPPDATA% move, profiles still live
    under ~/.hermes/profiles — fall back there when the computed root is absent."""
    computed = _get_default_hermes_home() / "profiles"
    native = Path.home() / ".hermes" / "profiles"
    if not computed.is_dir() and native.is_dir():
        return native
    return computed
```

`git add` each resolved file. **Do not commit**; Task 5 completes the patches.

---

## Task 5: Re-home the moved patches

**Executor:** Opus. Port the old code from `git show pre-v0.22.5-snapshot:<path>`.

- [ ] **Step 1: MC usage hook.** Find the new home with `git grep -n "session_cost_source = " -- agent/`. Insert our try/except block (`git show pre-v0.22.5-snapshot:agent/turn_usage.py | grep -n -A30 mission_control_reporter`) right after that assignment. Keep the bare `except Exception: pass`: reporting must never break a turn. Its inputs (`canonical_usage.*`, `cost_result.amount_usd`, `agent.model/provider/base_url`) must be in scope under the same names. If any were renamed, adapt the names, not the semantics.

- [ ] **Step 2: `MISSION_CONTROL_SESSION_ID`.** Find `_publish_session_id()` with `git grep -n "_publish_session_id" -- agent/`. In the session-state initializer, right after the `_publish_session_id()` call, add `os.environ["MISSION_CONTROL_SESSION_ID"] = session_id` unconditionally, as before (see the v0.21.5 Execution outcome, item 4).

- [ ] **Step 3: Paper-digest callbacks**

```bash
git show pre-v0.22.5-snapshot:plugins/platforms/telegram/adapter.py | grep -n -B2 -A40 "_handle_paper_feedback_callback"
git grep -n "def _handle_callback_query" -- plugins/ gateway/
```

1. Port `_handle_paper_feedback_callback(self, query, data, cb)` to the class or sibling that owns callback dispatch now. Bring along any module-level helpers and imports it uses.
2. Register it in upstream's prefix-dispatch structure with **exactly** the prefixes from the snapshot's dispatch entry: `(("accept:", "reject:", "rate:"), …)` if unchanged.
3. If upstream's dispatch table moved to a dict or registry, register through that. Never add an `if/elif` ladder (AGENTS.md rule).
4. Don't port any `update_prompt:` handling; upstream owns that.

- [ ] **Step 4: Nothing references removed symbols; syntax check**

```bash
git grep -n "mission_control_reporter" -- ':!docs' ; git grep -n "paper_feedback" -- plugins/ gateway/
git diff --cached --name-only --diff-filter=AM -- '*.py' | xargs python -c "import ast,sys;[ast.parse(open(f,encoding='utf-8').read(),f) for f in sys.argv[1:]]" && echo SYNTAX_OK
```

Expected: hits only in the files we intend, then `SYNTAX_OK`.

---

## Task 6: Verify the merge result, test, commit, push

**Executor:** Opus (the test run can go to Sonnet).

- [ ] **Step 1: The local-patch set is exactly what we intend**

```bash
git diff --name-status v0.22.5 -- . ':!docs/superpowers' | sort
```

Expected: **M** only for the files still patched (the Task 4 list minus anything retired, plus wherever Task 5 re-homed patches), and **A** for exactly our genuine additions listed in Pre-flight. **Any other `A` file is a resurrection** ([[hermes-v0206-upgrade]]): an upstream deletion that our side kept. Check each with `git log v2026.9.24..v0.22.5 --diff-filter=D -- <file>`; if upstream deleted it, `git rm` it. Every `M` diff must be small: `git diff v0.22.5 -- <file> | head -80`.

- [ ] **Step 2: Standing patch greps**

```bash
git grep -n "MISSION_CONTROL_SESSION_ID" -- agent/
git grep -n "mission_control_reporter" -- agent/
git grep -n "_handle_paper_feedback_callback" -- plugins/ gateway/   # def + dispatch entry
grep -n "chmod 666.*docker.sock" docker/stage2-hook.sh
grep -n "sync-assets" web/package.json
grep -n "uv sync" Dockerfile ; grep -c "extra hindsight" Dockerfile          # second: 0
grep -n -E "stop_grace_period|S6_SERVICES_GRACETIME" compose.hermes.local.yml
file docker/stage2-hook.sh docker/main-wrapper.sh                            # LF
```

- [ ] **Step 3: Targeted tests**, detached, one job ([[feedback-windows-heavy-jobs-sequential]])

```bash
powershell -c "Start-Process cmd -ArgumentList '/c','cd /d E:\GITHUB\projects\hermes-agent && bash scripts/run_tests.sh tests/hermes_cli/test_profiles.py tests/agent/ -k \"usage or session_id or agent_init\" -q > E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\tests.log 2>&1' -WindowStyle Hidden"
```

Then run the same for `tests/gateway/` Telegram callback tests: `git grep -l "_handle_callback_query" -- tests/`. The venv may need `source ./activate` (new `hermes pm` contributor flow) instead of `.venv`. If `scripts/run_tests.sh` can't find a venv, run `hermes pm doctor` and report. **Compare any failure against pure `v0.22.5`** in a throwaway worktree before calling it ours. The 4 known Windows-host `test_profiles.py` failures from v0.21.5 may persist.

- [ ] **Step 4: Commit the merge (two parents), push, add the plan**

```bash
git commit -m "Merge tag 'v0.22.5' (Hermes v0.21.5 -> v0.22.5)

Local patches re-homed after the v0.22 god-file split: <list from Task 5>.
Retired: <list, or 'none'>. Dockerfile: <honcho extra kept/dropped>.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
git cat-file -p HEAD | grep -c ^parent    # MUST be 2
git push origin main
git add -f docs/superpowers/plans/2026-10-29-hermes-v0225-upgrade.md && git commit -m "docs: v0.22.5 upgrade plan" && git push origin main
```

---

## Task 7: Rebuild the Hermes image

**Executor:** Haiku. Detached, the only heavy job running. Expect 15–30 min.

- [ ] **Step 1: Build**

```bash
powershell -c "Start-Process cmd -ArgumentList '/c','cd /d E:\GITHUB\projects\hermes-agent && docker compose -f docker-compose.yml -f compose.hermes.local.yml build gateway > E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\build.log 2>&1 & echo BUILD_EXIT=%ERRORLEVEL% >> E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\logs\build.log' -WindowStyle Hidden"
```

(`HERMES_UID`/`HERMES_GID` come from `.env` or compose defaults; if the old command passed them inline, set them with `set HERMES_UID=...&&` inside the cmd string.) Known failure signatures: an unknown extra in `uv sync` (Task 4 Dockerfile resolution wrong); `sync-assets` missing `@nous-research/ui` (v0.20.6 commit `a30148a14f`); a `hermes pm` hash-check failure.

- [ ] **Step 2: Verify inside the image** (`--entrypoint`, so s6 doesn't migrate anything)

```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint sh hermes-agent -c \
 'ls /opt/hermes/.venv/bin/python* ; /opt/hermes/.venv/bin/python -c "import sys;print(sys.version.split()[0])"; /opt/hermes/.venv/bin/hermes --version; /opt/hermes/.venv/bin/hermes plugins list 2>&1 | grep -i honcho'
```

Record the Python minor (Task 9 Step 6 depends on it) and whether Honcho is pre-installed or lazy-installs on first use.

- [ ] **Step 3: Sandbox images.** No rebuild needed (they're `FROM nikolaik/python-nodejs`). Confirm the configs weren't reset: `grep -n docker_image agents/*.yaml` → `coding: hermes-sandbox:rtk`, `research: hermes-sandbox:rtk-google` ([[hermes-sandbox-docker-cli]]).

---

## Task 8: Config migration and the Honcho plugin (host configs)

**Executor:** Sonnet.

- [ ] **Step 1: Migrate the host configs** with the new image (the stack is stopped):

```bash
export MSYS_NO_PATHCONV=1
docker run --rm --entrypoint /opt/hermes/.venv/bin/hermes -v C:/Users/Plamen/.hermes:/opt/data -e HERMES_HOME=/opt/data hermes-agent config migrate
docker run --rm --entrypoint /opt/hermes/.venv/bin/hermes -v C:/Users/Plamen/.hermes:/opt/data -e HERMES_HOME=/opt/data hermes-agent -p pilot config migrate
```

The container configs (`hermes-data/*`) migrate on first boot in Task 9.

- [ ] **Step 2: Semantic diff against the baseline**

```bash
B=/e/GITHUB/backups/hermes-pre-v0225-2026-10-29/baseline
python - $B/raw-default.yaml /c/Users/Plamen/.hermes/config.yaml <<'EOF'
import sys, yaml
def flat(d, p=""):
    for k, v in (d or {}).items():
        if isinstance(v, dict): yield from flat(v, f"{p}{k}.")
        else: yield f"{p}{k}", v
a, b = (dict(flat(yaml.safe_load(open(f, encoding="utf-8")))) for f in sys.argv[1:])
for k in sorted(a.keys() | b.keys()):
    if a.get(k) != b.get(k): print(f"{k}: {a.get(k)!r} -> {b.get(k)!r}")
EOF
```

Repeat for pilot. **Must be preserved:** `model.*` (including pilot's `base_url: http://host.docker.internal:11434/v1`), `memory.provider: honcho`, `terminal.backend: local` (both), `approvals.cron_mode: approve` (pilot), `platform_toolsets`, `database.journal_mode: delete`, `sessions.auto_prune: false`, `gateway.multiplex_profiles`. Report **every** other semantic change to the user. Past migrations silently reset personality and raised `delegation.max_iterations`. The changes `session_reset` removed (Task 3) and `_config_version` bumped are expected.

- [ ] **Step 3: Check for new opt-ins that default on.** Grep the migrated configs for `telemetry`, `shared_metrics` (must be off or absent), `cache_ttl`, `plugins.isolation`, `drop_pending_on_cold_boot`, and report their values.

---

## Task 9: Redeploy containers

**Executor:** Sonnet.

- [ ] **Step 1: Pre-empt stale-lock PermissionErrors** ([[hermes-stale-locks]]), with the stack stopped:

```bash
for a in coding research reviewer; do MSYS_NO_PATHCONV=1 docker run --rm -v E:/GITHUB/projects/hermes-data/$a:/d alpine chown -R 10000:10000 /d; done
```

- [ ] **Step 2: Recreate** (no `-v`!). First cont-init takes 3–5 min, plus any `state.db` migration. Healthy does not mean running.

```bash
docker compose -f docker-compose.yml -f compose.hermes.local.yml up -d --force-recreate
```

- [ ] **Step 3: Gateway topology and poller conflicts**

```bash
export MSYS_NO_PATHCONV=1
docker exec hermes ps -eo pid,args | grep "gateway run" | grep -v grep          # exactly ONE root gateway
docker exec hermes hermes gateway status
docker logs hermes 2>&1 | grep -i -E "multiplex|profile: pilot|boot.guard|Cron scheduler will tick" | tail -10
for c in hermes hermes-agent-forge-1 hermes-agent-research-1 hermes-agent-reviewer-1; do echo "== $c"; docker logs --since 15m $c 2>&1 | grep -i -E "conflict|terminated by other getUpdates" | tail -3; done
docker exec hermes-dashboard ps -eo pid,args | grep "gateway run" | grep -v grep # expect none
```

Expected: one gateway in `hermes` serving `['default', 'pilot']`, and no `getUpdates` conflict anywhere. **On any conflict:** `docker compose stop -t 60 gateway`, then re-check Task 3 Step 1.

- [ ] **Step 4: Config, env and sessions survived**

```bash
for c in hermes-agent-forge-1 hermes-agent-research-1 hermes-agent-reviewer-1; do echo -n "$c: "; docker exec $c printenv HERMES_WRITE_SAFE_ROOT; done   # /opt/data:/workspace
grep -H "_config_version" /e/GITHUB/projects/hermes-data/*/config.yaml /c/Users/Plamen/.hermes/config.yaml /c/Users/Plamen/.hermes/profiles/pilot/config.yaml
grep -H "auto_prune" /e/GITHUB/projects/hermes-data/*/config.yaml
```

Re-run Task 2 Step 3's session-count loop into `baseline/session-counts-after.txt` and `diff` it. **Counts must be ≥ before.** A drop means pruning ran: STOP and restore that `state.db` from the backup.

- [ ] **Step 5: Honcho through the plugin.** This is Review Focus #1.

```bash
for c in hermes hermes-agent-forge-1 hermes-agent-research-1 hermes-agent-reviewer-1; do echo "== $c"; docker exec $c hermes plugins list 2>&1 | grep -i honcho; docker exec $c hermes honcho status 2>&1 | tail -5; done
```

Every container must show the Honcho plugin enabled, and `honcho status` must show the **same workspace and peer ids as before** (compare with the `.hermes`/`hermes-data` backups' `honcho.json` or config). Then run a **recall probe**: ask one agent on Telegram "what do you remember about me?" and confirm it cites known facts. Finally, re-run the Task 2 Step 4 row-hash dump into `honcho-rows-after.tsv`: no existing row may be missing or changed (new rows are fine).

- [ ] **Step 6: Wiki-RAG.** This is Review Focus #3.

```bash
docker exec hermes-agent-research-1 test -f /opt/rag-data/.volume-ok && echo VOL_OK
wiki-rag "honcho memory upgrade"      # host shim: must return hits
```

Check `rag-health`: the Chroma count must equal the bm25 `chunks_fts` row count. **If Task 7 showed the Python minor changed (3.13 → 3.14)**, expect a `_vendor` import error: re-vendor per [[wiki-rag-system]] (pin the cosine space; no embedding prefixes), then re-run the query.

- [ ] **Step 7: Sandbox + docker.sock.** `docker exec hermes-agent-research-1 ls -la /var/run/docker.sock` must show `srw-rw-rw-`. Remove old sandbox containers by name (`docker ps -a --format '{{.Names}} {{.Image}}' | grep hermes-sandbox`).

---

## Task 10: Host-native install

**Executor:** Haiku. Detached.

- [ ] The host-native clone tracks the **fork**, so it follows the fork's `main`, not upstream stable (the notes say forks keep following `main`). Run `hermes update --plan` first and read it, then `hermes update` detached to a log. Known noise: `history diverged, resetting` (shallow clone, harmless), Node `EBADENGINE` (accepted), the `website/tsconfig.json` stash conflict. The new runtime may install Python 3.14 via `hermes pm`; check `hermes pm status` afterwards. Read `~/.hermes/logs/update_receipts/latest.json` for failed steps.
- [ ] `hermes --version` → v0.22.5, local = fork HEAD. `hermes profile list` → default + pilot. The updater may try to "fold per-profile gateways"; on the host there are none running, so it should be a no-op. Report it if it isn't.

---

## Task 11: End-to-end verification + memory

**Executor:** Sonnet for checks; the main session writes memory.

- [ ] **Step 1:** One real Telegram round-trip per bot: default, pilot, forge, research, reviewer.
- [ ] **Step 2: Paper-digest** (Review Focus #5): press a feedback button on a recent digest message. The adapter log must show the paper-feedback handler ran, with no "unknown callback".
- [ ] **Step 3: Cron.** `docker exec hermes hermes cron list`, and the same with `-p pilot`; compare with the baseline. Force one agent-mode job (`hermes -p pilot cron run pilot-morning-weekday`) and one `--no-agent --script` job (nightly-tracker, [[nightly-tracker-bot]]). Both must deliver. Watch for the new "loop guardrail" hard stops in cron output.
- [ ] **Step 4: Renamed tools** (Decision 6): `grep -rn -E "\b(todo|cronjob|process)\b" ~/.hermes/skills ~/.hermes/cron /e/GITHUB/projects/hermes-data/*/cron 2>/dev/null | grep -v node_modules | head`. Report the hits; change nothing.
- [ ] **Step 5:** After 30 min, check that `errors.log` in each HERMES_HOME has no new recurring errors, and that `hermes doctor` passes in each container.
- [ ] **Step 6: Memory.** Write `hermes-v0225-upgrade.md`, covering: the merge commit, the rollback tag, what each patch now lives in, Honcho-as-plugin behavior, Python minor plus RAG outcome, the auto-prune/session_reset decisions, and anything that diverged. Update [[hermes-post-update-checklist]] (new patch locations and greps), [[hermes-v0215-upgrade]] (superseded as baseline), [[wiki-rag-system]] (if re-vendored), and the `MEMORY.md` index. Append an **Execution outcome** section to this plan, commit it with `git add -f`, and push to origin.

---

## Rollback

1. `docker compose -f docker-compose.yml -f compose.hermes.local.yml stop -t 60`
2. `git checkout main && git reset --hard pre-v0.22.5-snapshot-2026-10-29`, then rebuild the image (Task 7).
3. Restore `hermes-data` and `.hermes` from `E:\GITHUB\backups\hermes-pre-v0225-2026-10-29\`. **This is required:** v0.22's migrated `state.db` and config are not guaranteed to be readable by v0.21.5. Restore `rag-data.tgz` into the volume only if it was re-vendored.
4. `up -d --force-recreate`. For the host-native install, run `hermes update` after the fork is reset. **Force-pushing the fork is the user's decision**; never do it automatically.
