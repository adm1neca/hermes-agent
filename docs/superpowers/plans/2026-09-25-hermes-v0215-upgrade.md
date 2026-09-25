# Hermes v0.20.6 → v0.21.5 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the `adm1neca/hermes-agent` fork and all deployed agents (default, pilot, forge/coding, research, reviewer) from v0.20.6 (`v2026.8.27`) to **v0.21.5 (`v2026.9.24`)**.

**Architecture:** Three phases. **Phase A (Tasks 1–2)**: safety net, plus defusing the one new runtime hazard (the profile multiplexer) *before* any new code runs. **Phase B (Tasks 3–5)**: real 3-way merge, conflict resolution, and re-homing the three patches whose hook points upstream moved. **Phase C (Tasks 6–10)**: image rebuild, config migration 39→46, redeploy, host-native update, verification + memory.

**Tech Stack:** Git (3-way merge), Docker + Compose (s6-overlay image), Python 3.13 / uv 0.11.19, Git Bash + PowerShell on Windows 10.

**Model routing (user preference: cheaper models where they suffice):**

| Task | Suggested executor | Why |
|---|---|---|
| 1, 6, 9 | Haiku subagent | Mechanical: backups, builds, `hermes update`, all with exact commands + expected output |
| 2, 7, 8, 10 | Sonnet subagent | Needs judgement reading logs/diffs, but no code authoring |
| 3, 4, 5 | Opus (main session) | Conflict resolution + re-homing patches into refactored modules |

---

## Pre-flight findings (verified 2026-09-25, all against live state)

- **Merge base is healthy.** `git merge-base HEAD v2026.9.24` = `5fc308a707…` = `v2026.8.27`; the v0.20.6 merge commit `e61592f1c1` has two parents. No squash-merge recurrence.
- **Fork is clean.** `git diff --name-status v2026.8.27 HEAD` = 10 M + 28 A = exactly the 33 genuine files recorded in `2026-08-31-artifacts/` + 5 docs. **No pre-merge cleanup phase is needed** (unlike v0.20.6).
- **Scale:** 15,742 upstream commits, 11,536 files changed. Upstream split god-files: `gateway/run.py` −29,657 lines, `agent/conversation_loop.py` −8,011, Telegram adapter −8,210.
- **Trial merge (`git merge-tree`) conflicts in 7 files**, all known local patches: `Dockerfile`, `agent/agent_init.py`, `agent/conversation_loop.py`, `gateway/run.py`, `hermes_cli/profiles.py`, `plugins/platforms/telegram/adapter.py`, `tools/environments/base.py`. `docker/stage2-hook.sh`, `web/package.json`, `.gitignore` auto-merge.
- **Config schema 39 → 46**, floor still 12. Every live config is at 39, so migrations run automatically. Notable: **m41** strips a "## Messaging other agents" block from SOUL.md (none of ours have it); **m45** appends a new `connections` toolset (`manage_connections` tool) to every saved `platform_toolsets` list.
- **Hindsight left the tree** (now `hermes plugins install hindsight`); the `hindsight` pyproject extra is **gone**. All live agents use `memory.provider: honcho`, so only the three unused host overlays (`~/.hermes/profiles/{forge,reviewer,scout}`) reference hindsight. Honcho stays in-tree and got a heavy rework (17 files, peer-model/session-routing changes).
- **Image Python unchanged** (`uv:0.11.6-python3.13-trixie` at both tags), so the wiki-RAG `_vendor` dir in the `rag-data` volume should stay ABI-compatible. Verify anyway (Task 8).
- `docker-compose.yml` unchanged upstream. `main-wrapper.sh` gets a `-p` argv fix; `stage2-hook.sh` adds XDG_RUNTIME_DIR handling; our docker.sock group block + `chmod 666` fallback are untouched.
- **Node engines** now `^22.22.0 || ^24.11.0 || >=26`. This machine has Node 22.20.0, so host-native web-UI refresh keeps failing `EBADENGINE`, same as v0.20.6 (user chose to leave it). Containers are unaffected.
- **state.db:** v0.21.0 rewrote the session store; v0.21.2 ("the state.db patch release") and v0.21.3 fixed its fragility. We land directly on v0.21.5, but first boot migrates every `state.db`, hence the offline backup in Task 1.

### ⚠ New runtime hazard: the profile multiplexer (MUST be defused before Task 8)

In v0.21.x, `gateway.multiplex_profiles` has only one valid value (a retired `false` is rewritten to `true`; commit `b936546561`), and multiplexing now works inside s6 containers (`b70ec27fa7`). The default gateway serves `profiles_to_serve(multiplex=True)` = **default + every named profile under `profiles/`**, skipping only profiles with a `gateway.parked` marker file or `gateway.standalone: true` in their config. `gateway_state.json: stopped` does **not** exclude a profile.

The `hermes` container mounts `C:\Users\Plamen\.hermes`, which still contains the vestigial pre-v0.15.2 profiles. Their Telegram tokens are **the same bots the live agent containers poll** (compared by sha1 prefix):

| Host profile (vestigial) | token hash | Live owner |
|---|---|---|
| `profiles/forge` | `60dd3edff9` | `forge` container (`agents/coding.env`) |
| `profiles/reviewer` | `cc6ba519a4` | `reviewer` container (`agents/reviewer.env`) |
| `profiles/scout` | `bb81b1b0a6` | `research` container (`agents/research.env`) |
| `profiles/pilot` | `50cf98eea2` | `gateway-pilot` s6 service in `hermes` (legit) |

Unmitigated, the upgraded `hermes` container would start second pollers for three live bots. That is a repeat of the v0.16.0 duplicate-gateway incident (polling conflicts, cross-wired crons). The `hermes-data/*` agent homes have no `profiles/` dir, so only the `hermes` container is exposed. Task 2 fixes this.

---

## Decisions (defaults chosen; override before executing)

1. **Vestigial forge/reviewer/scout host profiles.** **Default: archive.** Move them out of `profiles/` into the backup dir. That is the permanent fix [[hermes-v016-duplicate-gateways]] already recommended, and it also removes the only hindsight references. Alternative: leave them in place with a `gateway.parked` marker file each.
2. **Pilot placement under multiplexing.** **Default: `gateway.standalone: true`** in pilot's config. This keeps today's known-good topology (a separate `gateway-pilot` s6 process with its own `terminal.backend: local` and `approvals.cron_mode`). Alternative: let the default gateway absorb pilot (`hermes gateway migrate --multiplex`) and drop the s6 slot. That's upstream's direction, but it adds change to an upgrade that is already large.
3. **`connections` toolset (m45).** **Default: accept.** It adds one tool per API call. Decline by adding `connections` to `agent.disabled_toolsets` before migrating.
4. **Mission Control reporter hook.** Nothing has listened on :3333 since at least 2026-06 (no MC container). **Default: re-home it anyway.** It's try/except-wrapped and costs nothing. Alternative: retire it with `mission_control_reporter.py` and drop two patches permanently.
5. **Retire local Patch 2 (`tools/environments/base.py` win32 drain).** **Decided: retire.** It was already dead code at v0.18+, and upstream's new `base_output._drain_fd_windows()` uses `PeekNamedPipe`, which fixes the grandchild-holds-pipe gap our patch admitted it couldn't.

---

## Global Constraints

- **Fork:** `origin` = `adm1neca/hermes-agent`. **Upstream** is fetch-only; its push URL is `DISABLED_no_push_to_upstream`. Verify `git push --dry-run upstream main` fails before Task 3. Push **only** `origin main` ([[hermes-fork-push-policy]]).
- **Dev repo:** `E:\GITHUB\projects\hermes-agent`. **Host-native:** `C:\Users\Plamen\.hermes\hermes-agent` (tracks the fork).
- **Source tag** `v2026.8.27` (v0.20.6) → **target tag** `v2026.9.24` (v0.21.5). **Required merge-base:** `5fc308a70719a83cccdbba4c0e39c23f5a8239d5`. If it differs, STOP.
- **Pre-upgrade HEAD:** `399d71a6f4` (clean tree except the untracked `compose.hermes.local.yml.bak-20260911-104952`).
- **The Bash tool has a 2-minute default timeout.** Run `git merge`, `docker build`, and `hermes update` with `run_in_background: true`. An interrupted merge is finished with `rm .git/index.lock; git add -A; git commit`. Before committing, verify two parents with `git cat-file -p HEAD | head -4`.
- **Never** `docker compose down -v`. The named volume `hermes-agent_rag-data` holds the wiki-RAG index ([[wiki-rag-system]]).
- **Never** mount `docker.sock` into the `gateway` (`hermes`) service. That's a deliberate security decision recorded in `compose.hermes.local.yml`.
- Windows: `MSYS_NO_PATHCONV=1` for `docker exec … /opt/...`. Edits to `docker/*.sh` must stay LF. Use `--pathspec-from-file` for bulk git ops, never `grep -Ff`. Exclude `node_modules`/`.git`/`dist` from any grep.
- Commit after every task. Never amend. `.gitignore` excludes `docs/superpowers/*`, so use `git add -f` for plan files.

---

## Task 1: Safety net

**Executor:** Haiku. **No source changes.**

- [ ] **Step 1: Confirm starting state**

```bash
cd /e/GITHUB/projects/hermes-agent
git status --short                  # expect only: ?? compose.hermes.local.yml.bak-20260911-104952
git rev-parse --short HEAD          # expect 399d71a6f4
git merge-base HEAD v2026.9.24      # expect 5fc308a70719a83cccdbba4c0e39c23f5a8239d5
git push --dry-run upstream main    # MUST fail
```

- [ ] **Step 2: Remove stale fetch temp packs (~880 MB)**

Three `tmp_pack_*` files remain from interrupted fetches (2026-08-31 and 2026-09-25). No git process may be running.

```bash
tasklist | grep -i git || rm -f .git/objects/pack/tmp_pack_*
git fsck --connectivity-only 2>&1 | tail -3
```

- [ ] **Step 3: Rollback tag + branch**

```bash
git tag pre-v0.21.5-snapshot-2026-09-25
git branch pre-v0.21.5-snapshot
git push origin pre-v0.21.5-snapshot-2026-09-25 pre-v0.21.5-snapshot
```

- [ ] **Step 4: Record pre-upgrade effective configs (baseline for Task 7)**

Use a Windows path. Git Bash `/tmp` is invisible to Windows Python.

```bash
B=/c/Users/Plamen/AppData/Local/Temp/hermes-pre-v0215; mkdir -p $B
for p in default pilot; do hermes -p $p config show > $B/host-$p.yaml 2>&1 || echo "FAILED $p"; done
for a in coding research reviewer; do cp /e/GITHUB/projects/hermes-data/$a/config.yaml $B/container-$a.yaml; done
cp /c/Users/Plamen/.hermes/config.yaml $B/raw-default.yaml; cp /c/Users/Plamen/.hermes/profiles/pilot/config.yaml $B/raw-pilot.yaml
docker exec hermes ps -eo pid,args | grep "gateway run" > $B/gateways-before.txt
ls -la $B
```

- [ ] **Step 5: Offline backup of runtime state**

The first v0.21 boot migrates every `state.db`, so the copy must be consistent. Stop the Hermes stack (not honcho, scout or paper-digest), copy, and leave it stopped. Task 8 recreates it anyway.

```powershell
cd E:\GITHUB\projects\hermes-agent
docker compose -f docker-compose.yml -f compose.hermes.local.yml stop
robocopy "C:\Users\Plamen\.hermes" "E:\GITHUB\backups\hermes-pre-v0215-2026-09-25\.hermes" /E /R:1 /W:1 /XD hermes-agent node_modules
robocopy "E:\GITHUB\projects\hermes-data" "E:\GITHUB\backups\hermes-pre-v0215-2026-09-25\hermes-data" /E /R:1 /W:1
docker run --rm -v hermes-agent_rag-data:/v -v E:/GITHUB/backups/hermes-pre-v0215-2026-09-25:/b alpine tar czf /b/rag-data.tgz -C /v .
```

Robocopy exit codes 0–7 mean success. Expected: `FAILED: 0` on both, because nothing is locked with the stack stopped. **Downtime starts here.** Keep the gap to Task 8 short, or restart the stack now with `... up -d` if Phase B will take a while. Restarting is safe; nothing has changed yet.

---

## Task 2: Defuse the profile multiplexer (host-side, before any v0.21 code runs)

**Executor:** Sonnet. **Files:** `C:\Users\Plamen\.hermes\profiles\*` (runtime state, not the repo).

These changes are inert on v0.20.6. An unknown `gateway.standalone` key is deep-merged and ignored, so they're safe to do now.

- [ ] **Step 1: Archive the vestigial profiles (Decision 1)**

```powershell
$dst = "E:\GITHUB\backups\hermes-pre-v0215-2026-09-25\retired-profiles"
New-Item -ItemType Directory -Force $dst | Out-Null
foreach ($p in "forge","reviewer","scout") { Move-Item "C:\Users\Plamen\.hermes\profiles\$p" "$dst\$p" }
Get-ChildItem C:\Users\Plamen\.hermes\profiles   # expect: pilot only (plus any non-profile files)
```

If the Decision 1 alternative was chosen instead: `New-Item -ItemType File C:\Users\Plamen\.hermes\profiles\<p>\gateway.parked` for each of the three.

Check first that nothing references these profile dirs: `grep -rn "profiles/\(forge\|reviewer\|scout\)" /e/GITHUB/projects/hermes-agent/compose.hermes.local.yml ~/bin 2>/dev/null`. The `forge`/`reviewer` shell aliases from [[hermes-three-agent-setup]] may point at them. If so, note which ones break and tell the user.

- [ ] **Step 2: Mark pilot standalone (Decision 2)**

Add to `C:\Users\Plamen\.hermes\profiles\pilot\config.yaml`, merging into the existing `gateway:` mapping if present, otherwise as a new top-level section:

```yaml
gateway:
  standalone: true
```

Verify: `python -c "import yaml;print(yaml.safe_load(open(r'C:\Users\Plamen\.hermes\profiles\pilot\config.yaml'))['gateway'])"`.

- [ ] **Step 3: Record the decision** in the task output. Nothing to commit (runtime state).

---

## Task 3: Merge upstream v2026.9.24

**Executor:** Opus.

- [ ] **Step 1: Start the merge in the background**

```bash
cd /e/GITHUB/projects/hermes-agent
git -c merge.renameLimit=12000 merge v2026.9.24 --no-commit   # run_in_background: true
```

- [ ] **Step 2: Assert the conflict set matches the trial merge**

```bash
git diff --name-only --diff-filter=U | sort
```

Expected exactly (7):

```
Dockerfile
agent/agent_init.py
agent/conversation_loop.py
gateway/run.py
hermes_cli/profiles.py
plugins/platforms/telegram/adapter.py
tools/environments/base.py
```

If the count is materially different, STOP ([[feedback-plan-deviation-handling]]). Suspect a merge-base or rename-detection issue before resolving anything.

- [ ] **Step 3: Resolve each conflict**

Take upstream for the whole file, then re-apply our patch at its new location. That's cleaner than hunk-picking in heavily refactored files.

| File | Resolution |
|---|---|
| `tools/environments/base.py` | `git checkout --theirs` — **retire Patch 2** (Decision 5). Drain logic now lives in `tools/environments/base_output.py` (`_drain_fd_windows`, PeekNamedPipe). |
| `Dockerfile` | `--theirs`, then edit the `RUN uv sync` line to upstream's list **+ `--extra honcho`**: `... --extra azure-identity --extra matrix --extra google-chat --extra honcho`. **Do NOT keep `--extra hindsight`**: the extra no longer exists and `uv sync --frozen` would fail. Re-add our honcho comment paragraph next to upstream's rewritten "Catalog memory plugins" comment. |
| `hermes_cli/profiles.py` | `--theirs`, then replace the body of `_get_profiles_root()` (~line 174) with our Windows legacy fallback (still needed; `get_default_hermes_root()` is `%LOCALAPPDATA%\hermes` on Windows): see snippet A. |
| `gateway/run.py` | `--theirs`, then swap the exception order in `start_gateway`'s replace path (~line 5177): `except (ProcessLookupError, OSError): pass` / `except PermissionError: …`. Leave the `force=True` branch (~5190) alone. |
| `agent/agent_init.py` | `--theirs`, then add `os.environ["MISSION_CONTROL_SESSION_ID"] = session_id` at the end of `_publish_session_id()` (~line 1127), inside the root-agent path only (never for delegated children, mirroring the sibling `HERMES_SESSION_ID` fallback). |
| `agent/conversation_loop.py` | `--theirs`. The usage-accounting block moved out (see Task 4). |
| `plugins/platforms/telegram/adapter.py` | `--theirs`. Paper-digest is re-homed in Task 4. |

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

`git add` each file as it is resolved. **Do not commit yet** because Task 4 completes the patches.

---

## Task 4: Re-home the moved patches

**Executor:** Opus.

- [ ] **Step 1: Mission Control usage hook → `agent/turn_usage.py`** (Decision 4)

In `record_response_usage()`, insert our try/except block right after `agent.session_cost_source = cost_result.source` (~line 244), before the "Persist per-call token deltas" block. Port it verbatim from `git show HEAD:agent/conversation_loop.py`: search for `mission_control_reporter`. Its inputs (`canonical_usage.*`, `cost_result.amount_usd`, `agent.model/provider/base_url`) are in scope under the same names. Keep the bare `except Exception: pass` so reporting can never break a turn.

- [ ] **Step 2: Paper-digest callbacks → Telegram prefix-dispatch table**

Upstream's `_handle_callback_query` (~line 4700) now dispatches with `for prefix, handler in (...)` tuples, each handler taking `(query, data, cb)`.

1. Port `_handle_paper_feedback_callback` from `git show HEAD:plugins/platforms/telegram/adapter.py` as a method. Change its signature to `(self, query, data, cb)`.
2. Add its prefixes to the **second** dispatch tuple list, next to `("gt:", …)`/`("update_prompt:", …)`. Use exactly the prefixes our old code matched: read them from the old file, don't assume `accept:/reject:/rate:`.
3. **Do not** port our old inline `update_prompt:` handling. Upstream now has `_handle_update_prompt_callback`.
4. Port any module-level helpers or imports the old handler used (paper-digest API URL, etc.).

- [ ] **Step 3: Verify nothing else still references removed symbols**

```bash
git grep -n "mission_control_reporter" -- ':!docs' ; git grep -n -i "paper.digest\|paper_feedback" -- plugins/platforms/telegram/
python -c "import ast,sys;[ast.parse(open(f,encoding='utf-8').read()) for f in sys.argv[1:]]" \
  agent/turn_usage.py agent/agent_init.py gateway/run.py hermes_cli/profiles.py plugins/platforms/telegram/adapter.py && echo SYNTAX_OK
```

---

## Task 5: Verify the merge result, test, commit, push

**Executor:** Opus (tests can be handed to Sonnet).

- [ ] **Step 1: The local-patch set must be exactly what we intend**

```bash
git diff --name-status v2026.9.24 -- . ':!docs/superpowers' | sort
```

Expected: **M** `.gitignore`, `Dockerfile`, `agent/agent_init.py`, `agent/turn_usage.py`, `docker/stage2-hook.sh`, `gateway/run.py`, `hermes_cli/profiles.py`, `plugins/platforms/telegram/adapter.py`, `web/package.json`, plus **A** for the 23 genuine additions (`agents/*.yaml`, `docker/Dockerfile.sandbox*`, `mission_control_reporter.py`, `optional-skills/albert-heijn/**`, `skills/devops/telegram-callback-integration/**`, `upgrade-v016-plan.md`).
**Must NOT appear:** `tools/environments/base.py` (retired), `agent/conversation_loop.py` (moved). No other `A` files (which would be resurrections). Every `M` diff must be small; inspect with `git diff v2026.9.24 -- <file> | head -60`. A large, purely additive diff is a duplication artifact ([[hermes-v0206-upgrade]]).

- [ ] **Step 2: Standing patch greps**

```bash
grep -n "native.*is_dir" hermes_cli/profiles.py
grep -n "chmod 666.*docker.sock" docker/stage2-hook.sh
grep -n "threading.local" mission_control_reporter.py
grep -n "sync-assets" web/package.json
grep -n "extra honcho" Dockerfile ; grep -c "extra hindsight" Dockerfile   # second must print 0
grep -n "_handle_paper_feedback_callback" plugins/platforms/telegram/adapter.py   # def + dispatch entry
grep -n "MISSION_CONTROL_SESSION_ID" agent/agent_init.py
grep -n "mission_control_reporter" agent/turn_usage.py
file docker/stage2-hook.sh docker/main-wrapper.sh   # LF, not CRLF
```

- [ ] **Step 3: Targeted tests** (the full suite is impractically slow here)

```bash
scripts/run_tests.sh tests/hermes_cli/test_profiles.py tests/gateway/test_telegram*.py tests/agent/test_turn_usage*.py -q
```

Record pass/fail counts. Compare failures against the same files on `v2026.9.24` in a throwaway worktree before calling any failure ours.

- [ ] **Step 4: Commit the merge (two parents) and push**

```bash
git commit -m "Merge tag 'v2026.9.24' (Hermes v0.20.6 -> v0.21.5)

Local patches re-homed: MC usage hook -> agent/turn_usage.py; paper-digest
callbacks -> Telegram prefix-dispatch table. Retired: win32 drain patch in
tools/environments/base.py (superseded by base_output._drain_fd_windows).
Dockerfile: dropped removed 'hindsight' extra, kept 'honcho'."
git cat-file -p HEAD | grep -c ^parent    # MUST be 2
git push origin main
git add -f docs/superpowers/plans/2026-09-25-hermes-v0215-upgrade.md && git commit -m "docs: v0.21.5 upgrade plan" && git push origin main
```

---

## Task 6: Rebuild the Hermes image

**Executor:** Haiku. Background.

- [ ] **Step 1: Build**

```bash
cd /e/GITHUB/projects/hermes-agent
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose -f docker-compose.yml -f compose.hermes.local.yml build gateway   # run_in_background
```

Known failure signatures: an unknown `hindsight` extra (Task 3 Dockerfile resolution wrong), and `sync-assets` missing `@nous-research/ui` (check both `node_modules` locations, as in v0.20.6 commit `a30148a14f`).

- [ ] **Step 2: Verify in the built image** (use `--entrypoint`, or s6 runs a config migration)

```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint /opt/hermes/.venv/bin/python hermes-agent -c \
 "import honcho, sys; print('honcho ok', sys.version.split()[0])
import hermes_cli; from hermes_cli.config import DEFAULT_CONFIG; print('cfg', DEFAULT_CONFIG['_config_version'])"
```

Expected: `honcho ok 3.13.x`, `cfg 46`.

- [ ] **Step 3: Sandbox images: no rebuild needed.** `docker/Dockerfile.sandbox` is `FROM nikolaik/python-nodejs` + `COPY --from=docker:cli` and doesn't depend on Hermes source. Just confirm the configs weren't reset: `grep -n docker_image agents/*.yaml` → `coding: hermes-sandbox:rtk`, `research: hermes-sandbox:rtk-google`.

---

## Task 7: Config migration 39 → 46

**Executor:** Sonnet.

Configs in play: host root `~/.hermes/config.yaml` (default), `~/.hermes/profiles/pilot/config.yaml`, and the live container configs `hermes-data/{coding,research,reviewer}/config.yaml`.

- [ ] **Step 1: Decision 3.** If declining `connections`, add it to `agent.disabled_toolsets` in each config **before** migrating (m45 skips configs where it's disabled).

- [ ] **Step 2: Migrate the host configs** with the new code (`docker run --rm` against the host `.hermes` mount, or via the host-native install after Task 9). The container configs migrate on first boot in Task 8.

```bash
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint /opt/hermes/.venv/bin/hermes \
  -v C:/Users/Plamen/.hermes:/opt/data -e HERMES_HOME=/opt/data hermes-agent config migrate
MSYS_NO_PATHCONV=1 docker run --rm --entrypoint /opt/hermes/.venv/bin/hermes \
  -v C:/Users/Plamen/.hermes:/opt/data -e HERMES_HOME=/opt/data hermes-agent -p pilot config migrate
```

- [ ] **Step 3: Diff effective configs against the Task 1 baseline.** Key settings must be preserved: `model.*` (incl. pilot `base_url: http://host.docker.internal:11434/v1`), `memory.provider: honcho`, `terminal.backend` (pilot `local`), `terminal.docker_image`, `approvals.cron_mode` (pilot `approve`), `platform_toolsets`, `gateway.standalone` (pilot `true`). Expect `_config_version: 46` and `connections` appended (unless declined). Report every other semantic change. Last time, migrations silently reset personality and raised `delegation.max_iterations`.

---

## Task 8: Redeploy containers

**Executor:** Sonnet.

- [ ] **Step 1: Pre-empt stale-lock PermissionErrors** ([[hermes-stale-locks]]): the stack is stopped, so fix ownership via throwaway containers:

```bash
for a in coding research reviewer; do docker run --rm -v E:/GITHUB/projects/hermes-data/$a:/d alpine chown -R 10000:10000 /d; done
```

- [ ] **Step 2: Recreate** (no `-v`!)

```bash
HERMES_UID=$(id -u) HERMES_GID=$(id -g) docker compose -f docker-compose.yml -f compose.hermes.local.yml up -d --force-recreate
```

First cont-init can take 3–5 min (chown of venv). Healthy does **not** mean running. Check for `gateway run` processes.

- [ ] **Step 3: Gateway topology, the multiplexer check.** This is the most important verification.

```bash
export MSYS_NO_PATHCONV=1
docker exec hermes ps -eo pid,args | grep "gateway run" | grep -v grep
docker exec hermes hermes gateway status
docker logs hermes 2>&1 | grep -i -E "multiplex|standalone|served_profiles|polling conflict|Conflict" | tail -20
for c in hermes-agent-forge-1 hermes-agent-research-1 hermes-agent-reviewer-1; do echo "== $c"; docker logs --since 10m $c 2>&1 | grep -i -E "conflict|terminated by other getUpdates" | tail -3; done
docker exec hermes-dashboard ps -eo pid,args | grep "gateway run" | grep -v grep   # expect none
```

Expected: `hermes` runs the default gateway + a separate `-p pilot gateway run` (standalone). The served-profiles log line lists **only default**. No `Conflict: terminated by other getUpdates` anywhere. On any polling conflict, STOP, run `docker compose stop gateway`, and re-check Task 2.

- [ ] **Step 4: Config and env survived**

```bash
for c in hermes-agent-forge-1 hermes-agent-research-1 hermes-agent-reviewer-1; do echo -n "$c: "; docker exec $c printenv HERMES_WRITE_SAFE_ROOT; done   # /opt/data:/workspace
grep -H "_config_version" /e/GITHUB/projects/hermes-data/*/config.yaml   # 46
```

- [ ] **Step 5: Honcho (reworked upstream).** In each of `hermes`, forge, research, reviewer: `docker exec <c> hermes honcho status` should show connected with the right workspace/peer. Send one Telegram message to one agent and confirm a Honcho write in `honcho-api-1` logs. Watch for new peer-model config warnings in `errors.log`.

- [ ] **Step 6: Wiki-RAG.** `docker exec hermes-agent-research-1 test -f /opt/rag-data/.volume-ok && echo VOL_OK`, then run a `wiki-rag` query from the host shim and check `rag-health`. Chroma count must equal bm25 `chunks_fts` rows. An import error from `_vendor` means the Python ABI changed after all: re-vendor per [[wiki-rag-system]].

- [ ] **Step 7: Sandbox + docker.sock.** `docker exec hermes-agent-research-1 ls -la /var/run/docker.sock` → `srw-rw-rw-`. Remove sandbox containers left from the old image by name (`docker ps -a --format '{{.Names}} {{.Image}}' | grep hermes-sandbox`), because an `ancestor=` filter misses dangling images.

---

## Task 9: Host-native install

**Executor:** Haiku. Background.

- [ ] Run `hermes update --plan` first (new read-only inventory in v0.21), then `hermes update`. Expected known noise: `website/tsconfig.json` stash conflict (benign), Node `EBADENGINE` on web deps (Node 22.20 < 22.22; accepted). The new updater writes a receipt: check `~/.hermes/logs/update_receipts/latest.json` for failed steps. The updater's fleet-version check may flag the *container* gateways as not updatable in place (docker kind). That's expected, not a failure.
- [ ] `hermes --version` → `v0.21.5 (2026.9.24)`, local = fork HEAD. `hermes profile list` → default + pilot (forge/reviewer/scout archived).

---

## Task 10: End-to-end verification + memory update

**Executor:** Sonnet for checks; main session writes memory.

- [ ] One real Telegram round-trip per bot: default, pilot, forge, research, reviewer.
- [ ] Paper-digest: trigger or press a feedback button on a recent digest message and confirm the callback reaches the handler (adapter log line, no "unknown callback").
- [ ] Cron: `docker exec hermes hermes cron list` and the same for `-p pilot`. Force one agent-mode job (`hermes -p pilot cron run pilot-morning-weekday`) and one `--no-agent --script` job (nightly-tracker) and confirm both deliver. Watch for new "protected instruction file requires approval" denials (v0.21.0 #81152) in agent-mode crons that write skills/memory.
- [ ] After 30 min: `errors.log` in each HERMES_HOME has no new recurring errors. Check state.db health with `hermes doctor` in each container (v0.21.0 store rewrite).
- [ ] Update memory: new `hermes-v0215-upgrade.md` covering the multiplexer hazard + decision, the hindsight extra removal, patch relocations (turn_usage.py, Telegram dispatch table), Patch 2 retired, and config 46. Update [[hermes-windows-patches]] (Patch 2 retired), [[hermes-post-update-checklist]] (new patch locations + greps), [[hermes-pilot-profile]] (`gateway.standalone`), [[hermes-v016-duplicate-gateways]] (stale profiles now archived), and the MEMORY.md index.

---

## Rollback

1. `docker compose -f docker-compose.yml -f compose.hermes.local.yml stop`
2. `git checkout main && git reset --hard pre-v0.21.5-snapshot-2026-09-25`, rebuild the image (Task 6).
3. Restore `hermes-data` and `.hermes` from `E:\GITHUB\backups\hermes-pre-v0215-2026-09-25\`. **Required:** v0.21's migrated `state.db` and config v46 are not guaranteed readable by v0.20.6. Restore the retired profiles only if also rolling back Task 2's intent.
4. `up -d --force-recreate`; host-native: `git -C ~/.hermes/hermes-agent reset --hard e61592f1c1` or `hermes update` after the fork is reset. Force-pushing the fork is a user decision; don't do it automatically.
