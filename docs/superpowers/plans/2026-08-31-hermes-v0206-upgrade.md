# Hermes v0.19.0 → v0.20.6 Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the `adm1neca/hermes-agent` fork and all five deployed agents from v0.19.0 (`v2026.7.20`) to v0.20.6 (`v2026.8.27`), while first repairing the duplication damage the v0.19.0 merge left in the fork.

**Architecture:** Three phases. **Phase A (Tasks 1–5)** resets the fork to "upstream `v2026.7.20` + only the 33 genuinely-local files", removing 71 resurrected files, 26 artifact-only modifications, and — critically — a live double-spawned gateway watcher bug. **Phase B (Tasks 6–8)** performs the real 3-way merge of `v2026.8.27` and resolves the config-schema floor. **Phase C (Tasks 9–13)** rebuilds images, updates the host-native install, redeploys, and verifies every agent.

Phase A is what makes Phase B safe: after cleanup the merge conflicts only on genuinely-patched files, instead of silently carrying 200+ artifact lines forward into another release.

**Tech Stack:** Git (3-way merge), Docker + Docker Compose, Python 3.13 / uv, PowerShell + Git Bash on Windows 10.

## Global Constraints

- **Fork:** `origin` = `git@github.com:adm1neca/hermes-agent.git`. **Upstream:** `upstream` = `git@github.com:NousResearch/hermes-agent.git`.
- **Dev repo:** `E:\GITHUB\projects\hermes-agent`. **Host-native install:** `C:\Users\Plamen\.hermes\hermes-agent` (tracks the fork, not upstream).
- **Source tag:** `v2026.7.20` (v0.19.0). **Target tag:** `v2026.8.27` (v0.20.6).
- **Verified merge-base:** `git merge-base HEAD v2026.8.27` MUST return `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`. If it returns anything else, STOP — the squash-merge failure mode has recurred.
- **Config floor:** upstream `SUPPORT_FLOOR_VERSION = 12`; target default `_config_version: 39`. Profile overlays sit at `10` and must be bumped to `12` before migration can run.
- **Never edit `docker/entrypoint.sh` or `docker/stage2-hook.sh` on Windows without re-normalizing line endings** — CRLF breaks the container shebang. Fix procedure in Task 9 Step 1.
- **The Bash tool has a 2-minute timeout.** `git merge`, `docker build`, and `hermes update` WILL exceed it. Run them with `run_in_background: true`, or expect to finish an interrupted merge manually (`rm .git/index.lock; git add -A; git commit`).
- **Do not use `grep -Ff` for bulk file operations.** One filename can be a substring of another; this produced a silent double-count during the v0.19.0 upgrade. Always use `git ... --pathspec-from-file=<list>`.
- Commit after every task. Never amend.

---

## File Classification Reference

All lists below are **derived, not hand-maintained** — the v0.19.0 upgrade proved a hand-maintained patch table is not trustworthy. Task 2 regenerates them and asserts the counts. If a count differs from what is stated here, STOP and re-derive: the tree is not in the state this plan assumes.

**Category GENUINE-MODIFIED (10 files)** — carry a real local patch that must survive the merge:

| File | The genuine patch |
|---|---|
| `.gitignore` | `agents/*.env` and `.claude/` entries |
| `Dockerfile` | `--extra honcho` on the `uv sync` line |
| `docker/stage2-hook.sh` | `chmod 666 /var/run/docker.sock` block |
| `hermes_cli/profiles.py` | `_get_profiles_root()` falls back to `~/.hermes/profiles` |
| `tools/environments/base.py` | Windows `sys.platform == "win32"` drain branch |
| `plugins/platforms/telegram/adapter.py` | Paper-digest feedback callbacks (13 refs) |
| `agent/agent_init.py` | `MISSION_CONTROL_SESSION_ID` env assignment **only** |
| `agent/conversation_loop.py` | `mission_control_reporter.report_usage()` hook |
| `web/package.json` | `sync-assets`/`predev`/`prebuild` scripts + `shx` dep |
| `gateway/run.py` | `except (ProcessLookupError, OSError)` Windows fix **only** |

**Category GENUINE-ADDED (23 files)** — local additions, keep as-is:
`agents/coding-config.yaml`, `agents/research-config.yaml`, `agents/reviewer-config.yaml`, `agents/scout-config.yaml`, `docker/Dockerfile.sandbox`, `docker/Dockerfile.sandbox.research`, `mission_control_reporter.py`, `optional-skills/albert-heijn/**` (13 files), `skills/devops/telegram-callback-integration/**` (2 files), `upgrade-v016-plan.md`

**Category ARTIFACT (97 files)** — remove entirely:
- **71 STALE-ADDED**: present in `v2026.7.1`, deleted upstream by `v2026.7.20`, resurrected by the v0.19.0 merge resolving delete-conflicts as "keep ours". Still absent in `v2026.8.27`.
- **26 ARTIFACT-MODIFIED**: purely-additive duplication — `locales/*.yaml` (16, duplicated `credits: not_logged_in:` block), `agent/lsp/install.py`, `hermes_cli/debug.py`, `hermes_cli/kanban_db.py`, and 7 files under `tests/`.

**Mixed files needing surgery (3):** `gateway/run.py`, `agent/agent_init.py`, and `plugins/platforms/telegram/adapter.py` each contain BOTH a genuine patch and duplication artifacts. Task 5 handles them individually.

---

## Task 1: Establish the safety net

**Files:**
- Create: `E:\GITHUB\backups\hermes-pre-v0206-2026-08-31\` (backup target)
- No source files modified.

**Interfaces:**
- Produces: tag `pre-v0.20.6-snapshot-2026-08-31` and branch `pre-v0.20.6-snapshot`, both at pre-upgrade fork HEAD `827d93f13`; plus `/tmp/hermes-preupgrade/*.yaml`, the effective-config baseline Task 8 diffs against.

- [ ] **Step 1: Confirm the tree is clean and HEAD is where this plan expects**

```bash
cd /e/GITHUB/projects/hermes-agent
git status --short
git rev-parse HEAD
```

Expected: `git status --short` prints nothing; `git rev-parse HEAD` starts with `827d93f13`.
If the tree is dirty, STOP and ask the user — do not stash. Uncommitted work here could be an unrecorded local patch.

- [ ] **Step 2: Verify the merge-base is intact (the v0.19.0 lesson)**

```bash
git merge-base HEAD v2026.8.27
git cat-file -p HEAD | head -4
```

Expected: merge-base is `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`, and `git cat-file -p HEAD` shows **two** `parent` lines.
A single `parent` line means HEAD is a squash and this plan's conflict predictions are void — STOP.

- [ ] **Step 3: Create the rollback tag and branch**

```bash
git tag pre-v0.20.6-snapshot-2026-08-31
git branch pre-v0.20.6-snapshot
git push origin pre-v0.20.6-snapshot-2026-08-31
git push origin pre-v0.20.6-snapshot
```

- [ ] **Step 4: Back up live runtime state**

Runtime state lives outside the repo and is NOT covered by the git tag.

```powershell
robocopy "C:\Users\Plamen\.hermes" "E:\GITHUB\backups\hermes-pre-v0206-2026-08-31\.hermes" /E /R:1 /W:1
robocopy "E:\GITHUB\projects\hermes-data" "E:\GITHUB\backups\hermes-pre-v0206-2026-08-31\hermes-data" /E /R:1 /W:1
```

Robocopy exit codes 0–7 are success; 8 or higher is a real failure.

- [ ] **Step 5: Record pre-upgrade effective configs for later comparison**

Task 8 needs a before/after diff of each profile's *effective* config.

```bash
mkdir -p /tmp/hermes-preupgrade
for p in default forge pilot reviewer scout; do
  hermes -p "$p" config show > "/tmp/hermes-preupgrade/$p.yaml" 2>&1 || echo "FAILED: $p"
done
ls -la /tmp/hermes-preupgrade/
```

Expected: five non-empty files. If `config show` is not a valid subcommand on v0.19.0, fall back to copying each `~/.hermes/profiles/<p>/config.yaml` — and note in the task output which method was used, because Task 8 Step 5 must compare like with like.

- [ ] **Step 6: Verify the safety net exists**

```bash
git status --short && git tag --list 'pre-v0.20.6*' && git branch --list 'pre-v0.20.6*'
```

Expected: clean tree, tag and branch both present. Nothing to commit in this task.

---

## Task 2: Regenerate and assert the file classification

**Files:**
- Create: `/tmp/hermes-cleanup/{local-diff,stale,genuine-added,genuine-mod,artifact-mod}.txt`
- Create: `docs/superpowers/plans/2026-08-31-artifacts/` (committed record)

**Interfaces:**
- Produces: the pathspec files Tasks 3–5 consume. These MUST be generated here, never typed by hand.

- [ ] **Step 1: Generate the raw local diff against the source tag**

```bash
cd /e/GITHUB/projects/hermes-agent
mkdir -p /tmp/hermes-cleanup
git diff --name-status v2026.7.20 HEAD > /tmp/hermes-cleanup/local-diff.txt
cut -f1 /tmp/hermes-cleanup/local-diff.txt | sort | uniq -c
```

Expected exactly:

```
     94 A
     36 M
```

- [ ] **Step 2: Split added files into STALE vs GENUINE by presence in `v2026.7.1`**

A file that existed in `v2026.7.1` but not in `v2026.7.20` was deleted upstream and resurrected by the bad merge.

```bash
cd /e/GITHUB/projects/hermes-agent
rm -f /tmp/hermes-cleanup/stale.txt /tmp/hermes-cleanup/genuine-added.txt
while IFS=$'\t' read -r st f; do
  [ "$st" = "A" ] || continue
  if git cat-file -e "v2026.7.1:$f" 2>/dev/null; then
    echo "$f" >> /tmp/hermes-cleanup/stale.txt
  else
    echo "$f" >> /tmp/hermes-cleanup/genuine-added.txt
  fi
done < /tmp/hermes-cleanup/local-diff.txt
wc -l < /tmp/hermes-cleanup/stale.txt
wc -l < /tmp/hermes-cleanup/genuine-added.txt
```

Expected: `71` stale, `23` genuine-added. If these differ, STOP and re-derive.

- [ ] **Step 3: Build the artifact-modified list**

The 26 artifact-only files are every modified file EXCEPT the 10 genuine ones.

```bash
cd /e/GITHUB/projects/hermes-agent
grep '^M	' /tmp/hermes-cleanup/local-diff.txt | cut -f2 | sort > /tmp/hermes-cleanup/all-mod.txt
cat > /tmp/hermes-cleanup/genuine-mod.txt <<'EOF'
.gitignore
Dockerfile
agent/agent_init.py
agent/conversation_loop.py
docker/stage2-hook.sh
gateway/run.py
hermes_cli/profiles.py
plugins/platforms/telegram/adapter.py
tools/environments/base.py
web/package.json
EOF
sort -o /tmp/hermes-cleanup/genuine-mod.txt /tmp/hermes-cleanup/genuine-mod.txt
comm -23 /tmp/hermes-cleanup/all-mod.txt /tmp/hermes-cleanup/genuine-mod.txt > /tmp/hermes-cleanup/artifact-mod.txt
wc -l < /tmp/hermes-cleanup/artifact-mod.txt
cat /tmp/hermes-cleanup/artifact-mod.txt
```

Expected: `26` lines — 16 `locales/*.yaml`, `agent/lsp/install.py`, `hermes_cli/debug.py`, `hermes_cli/kanban_db.py`, and 7 `tests/` files.

- [ ] **Step 4: Sanity-check the arithmetic**

```bash
echo $(( $(wc -l < /tmp/hermes-cleanup/stale.txt) + $(wc -l < /tmp/hermes-cleanup/genuine-added.txt) ))
echo $(( $(wc -l < /tmp/hermes-cleanup/artifact-mod.txt) + $(wc -l < /tmp/hermes-cleanup/genuine-mod.txt) ))
```

Expected: `94` then `36`. A mismatch means the lists are inconsistent — STOP.

- [ ] **Step 5: Commit the classification as a working record**

```bash
cd /e/GITHUB/projects/hermes-agent
mkdir -p docs/superpowers/plans/2026-08-31-artifacts
cp /tmp/hermes-cleanup/stale.txt /tmp/hermes-cleanup/artifact-mod.txt \
   /tmp/hermes-cleanup/genuine-mod.txt /tmp/hermes-cleanup/genuine-added.txt \
   docs/superpowers/plans/2026-08-31-artifacts/
git add -f docs/superpowers/plans/2026-08-31-artifacts/
git commit -m "docs: record v0.19.0 merge-damage file classification for the v0.20.6 upgrade"
```

`-f` is required because `.gitignore` excludes `docs/superpowers/*`.

---

## Task 3: Remove the 71 resurrected files

**Files:**
- Delete: the 71 paths in `/tmp/hermes-cleanup/stale.txt`

**Interfaces:**
- Consumes: `/tmp/hermes-cleanup/stale.txt` from Task 2.
- Produces: a tree with no files upstream deleted before `v2026.7.20`.

- [ ] **Step 1: Prove every listed file is genuinely absent from the target**

Deleting a file upstream still ships would break the build. Assert absence from `v2026.8.27` first.

```bash
cd /e/GITHUB/projects/hermes-agent
bad=0
while read -r f; do
  if git cat-file -e "v2026.8.27:$f" 2>/dev/null; then echo "PRESENT UPSTREAM: $f"; bad=1; fi
done < /tmp/hermes-cleanup/stale.txt
echo "violations=$bad"
```

Expected: `violations=0` with no `PRESENT UPSTREAM` lines. Any hit means that file is NOT stale — remove it from the list and re-derive.

- [ ] **Step 2: Confirm nothing in the surviving tree references them**

```bash
cd /e/GITHUB/projects/hermes-agent
while read -r f; do
  base=$(basename "$f"); stem="${base%.*}"
  case "$stem" in *.test|*.spec) continue;; esac
  hits=$(grep -rlF "$stem" --include=*.py --include=*.ts --include=*.tsx --include=*.cjs --include=*.js . 2>/dev/null \
         | grep -vFf /tmp/hermes-cleanup/stale.txt | head -3)
  [ -n "$hits" ] && { echo "REFERENCED: $f"; echo "$hits" | sed 's/^/    /'; }
done < /tmp/hermes-cleanup/stale.txt
```

Expected: no output, or only incidental matches on generic stems. Investigate any hit in a non-test source file before deleting, and record the finding in the task output.

- [ ] **Step 3: Delete them in one pathspec operation**

```bash
cd /e/GITHUB/projects/hermes-agent
git rm --quiet --pathspec-from-file=/tmp/hermes-cleanup/stale.txt
git status --short | wc -l
```

Expected: `71` staged deletions.

- [ ] **Step 4: Verify the Python package still imports**

```bash
cd /e/GITHUB/projects/hermes-agent
python -c "import hermes_cli.config, hermes_cli.profiles, gateway.run; print('imports OK')"
```

Expected: `imports OK`. An `ImportError` naming a deleted module means Step 2 missed a reference — restore that file and re-derive.

- [ ] **Step 5: Commit**

```bash
git commit -m "fix: drop 71 files resurrected by the v0.19.0 squash-conflict resolution

These existed in v2026.7.1, were deleted upstream by v2026.7.20, and were
re-added when delete-conflicts were resolved as 'keep ours'. All 71 are
still absent in v2026.8.27."
```

---

## Task 4: Clean the artifact-only modifications

**Files:**
- Modify (reset to `v2026.7.20` content): the 26 paths in `/tmp/hermes-cleanup/artifact-mod.txt`

**Interfaces:**
- Consumes: `/tmp/hermes-cleanup/artifact-mod.txt` from Task 2.

- [ ] **Step 1: Confirm every artifact file's local diff is purely additive**

Duplication only ever adds lines. A deletion would mean a real local edit hiding in this list.

```bash
cd /e/GITHUB/projects/hermes-agent
git diff --numstat v2026.7.20 HEAD -- $(tr '\n' ' ' < /tmp/hermes-cleanup/artifact-mod.txt) \
  | awk '$2 != 0 {print "HAS DELETIONS: "$3}'
```

Expected: no output. Any file printed has a real local edit — move it to `genuine-mod.txt` and handle it in Task 5 instead.

- [ ] **Step 2: Reset all 26 to the upstream `v2026.7.20` content**

```bash
cd /e/GITHUB/projects/hermes-agent
git checkout v2026.7.20 -- $(tr '\n' ' ' < /tmp/hermes-cleanup/artifact-mod.txt)
git diff --cached --numstat | wc -l
```

Expected: `26`.

- [ ] **Step 3: Verify the duplicated locale block is gone**

```bash
cd /e/GITHUB/projects/hermes-agent
grep -c "not_logged_in" locales/en.yaml
```

Expected: `1` (was `2`).

- [ ] **Step 4: Verify the duplicated Python definitions are gone**

```bash
cd /e/GITHUB/projects/hermes-agent
for f in hermes_cli/debug.py hermes_cli/kanban_db.py agent/lsp/install.py; do
  echo -n "$f differs-from-tag lines: "; git diff --numstat v2026.7.20 HEAD -- "$f" | wc -l
done
echo -n "_run_debug_share_nous: "; grep -c "def _run_debug_share_nous" hermes_cli/debug.py
echo -n "stdin=DEVNULL: "; grep -c "stdin=subprocess.DEVNULL" agent/lsp/install.py
```

Expected: each file reports `0` differing lines; `_run_debug_share_nous` is `1`; `stdin=subprocess.DEVNULL` is `2` (the third occurrence was itself a resurrection of a line upstream removed).

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: revert 26 files to upstream v2026.7.20 (duplicated-block artifacts)

The v0.19.0 merge duplicated blocks into 16 locale files and 10 Python
files. None carried a genuine local patch; all are reset to the tag."
```

---

## Task 5: Surgically clean the 3 mixed files

**Files:**
- Modify: `gateway/run.py`, `agent/agent_init.py`, `plugins/platforms/telegram/adapter.py`

**Interfaces:**
- Produces: these three files contain their genuine local patch and nothing else. This is the task that fixes the live double-watcher bug.

### 5a — `gateway/run.py`

Its ONLY genuine patch is the Windows exception fix. The other 202 inserted lines are artifact, including two duplicate `create_task` watcher spawns.

- [ ] **Step 1: Reset to the tag, then re-apply the single genuine patch**

```bash
cd /e/GITHUB/projects/hermes-agent
git checkout v2026.7.20 -- gateway/run.py
python - <<'PY'
import io
p = "gateway/run.py"
s = io.open(p, encoding="utf-8").read()
old = """            except ProcessLookupError:
                pass  # Already gone
            except (PermissionError, OSError):"""
new = """            except (ProcessLookupError, OSError):
                pass  # Already gone or invalid PID on Windows
            except PermissionError:"""
assert s.count(old) == 1, f"expected exactly 1 match, found {s.count(old)}"
io.open(p, "w", encoding="utf-8", newline="").write(s.replace(old, new))
print("patch re-applied")
PY
```

Expected: `patch re-applied`. An assertion failure means the surrounding block differs from what this plan recorded — inspect before proceeding.

- [ ] **Step 2: Verify the duplication is gone and the patch is present**

```bash
cd /e/GITHUB/projects/hermes-agent
echo "--- duplicate defs (each must be 1) ---"
for d in _async_delegation_watcher _enrich_async_delegation_routing _restore_moa_one_shot _pause_typing_before_finalize _refresh_agent_cache_message_count; do
  echo -n "$d: "; grep -cE "^    (async )?def $d\b" gateway/run.py
done
echo -n "bare create_task spawns (must be 0): "
grep -cE "asyncio\.create_task\(self\._(async_delegation|drain_control)_watcher" gateway/run.py
echo -n "supervised spawns (must be 2): "
grep -cE "_spawn_supervised\(self\._(async_delegation|drain_control)_watcher" gateway/run.py
echo -n "genuine patch present (must be 1): "
grep -c "invalid PID on Windows" gateway/run.py
```

- [ ] **Step 3: Confirm the file parses**

```bash
cd /e/GITHUB/projects/hermes-agent
python -c "import ast,io; ast.parse(io.open('gateway/run.py',encoding='utf-8').read()); print('parses OK')"
```

### 5b — `agent/agent_init.py`

The genuine patch is the `MISSION_CONTROL_SESSION_ID` line only. The `platform_hints` block is artifact — upstream already ships that feature in both `agent_init.py` and `agent/system_prompt.py`.

- [ ] **Step 4: Reset to the tag**

```bash
cd /e/GITHUB/projects/hermes-agent
git checkout v2026.7.20 -- agent/agent_init.py
echo -n "platform_hint refs (upstream's own copy, expect 6): "
grep -c "platform_hint" agent/agent_init.py
grep -n "agent.session_id" agent/agent_init.py | head -5
```

- [ ] **Step 5: Re-apply the Mission Control line**

Insert immediately after the first statement that assigns `agent.session_id`, matching the surrounding indentation:

```python
    # Mission Control reporter (local) reads MISSION_CONTROL_SESSION_ID from
    # the env to attribute per-turn cost reports to this run.  Kept distinct
    # from HERMES_SESSION_ID so MC tracking is opt-in via the local reporter
    # module and won't surprise upstream-style deployments.
    os.environ["MISSION_CONTROL_SESSION_ID"] = agent.session_id
```

- [ ] **Step 6: Verify**

```bash
cd /e/GITHUB/projects/hermes-agent
echo -n "MISSION_CONTROL_SESSION_ID (expect 1): "; grep -c "MISSION_CONTROL_SESSION_ID" agent/agent_init.py
echo -n "platform_hint (expect 6): "; grep -c "platform_hint" agent/agent_init.py
echo -n "os imported: "; grep -cE "^import os$" agent/agent_init.py
python -c "import ast,io; ast.parse(io.open('agent/agent_init.py',encoding='utf-8').read()); print('parses OK')"
```

If `os` is not imported at module level, add `import os` alongside the other stdlib imports.

### 5c — `plugins/platforms/telegram/adapter.py`

The genuine patch is the paper-digest callbacks (13 references, absent from upstream in both `v2026.7.20` and `v2026.8.27`). The artifacts are two duplicated methods.

- [ ] **Step 7: Locate the duplicates and prove the copies are identical**

Do NOT reset this file — the paper-digest patch is large and spans four hunks. Delete the duplicates in place.

```bash
cd /e/GITHUB/projects/hermes-agent
python - <<'PY'
import io, re
p = "plugins/platforms/telegram/adapter.py"
lines = io.open(p, encoding="utf-8").read().splitlines(keepends=True)
def block(start):
    j = start + 1
    while j < len(lines) and not re.match(r"    (async )?def ", lines[j]):
        j += 1
    return "".join(lines[start:j])
for name in ("_disarm_ptb_retry_loop", "_truncate_stream_overflow_preview"):
    idx = [i for i, l in enumerate(lines) if re.match(rf"    (async )?def {name}\b", l)]
    print(name, "at lines", [i + 1 for i in idx],
          "identical:" , block(idx[0]).strip() == block(idx[1]).strip() if len(idx) == 2 else "N/A")
PY
```

Expected: each method reports two line numbers and `identical: True`. If they are NOT identical, STOP — the copies have diverged and a human must choose which to keep.

- [ ] **Step 8: Delete the second definition of each method**

For each method, remove the **second** `def` line and its body (the block runs from that `def` line to the line before the next same-indentation `def`).

- [ ] **Step 9: Verify the adapter after surgery**

```bash
cd /e/GITHUB/projects/hermes-agent
for d in _disarm_ptb_retry_loop _truncate_stream_overflow_preview; do
  echo -n "$d (expect 1): "; grep -cE "def $d\b" plugins/platforms/telegram/adapter.py
done
echo -n "paper-digest refs (expect 13): "
grep -ciE "paper.digest|paper_digest" plugins/platforms/telegram/adapter.py
python -c "import ast,io; ast.parse(io.open('plugins/platforms/telegram/adapter.py',encoding='utf-8').read()); print('parses OK')"
```

- [ ] **Step 10: Full-tree verification — fork should now be tag + genuine only**

```bash
cd /e/GITHUB/projects/hermes-agent
git add -A
git diff --cached --name-only v2026.7.20 | sort > /tmp/hermes-cleanup/after.txt
cat /tmp/hermes-cleanup/genuine-mod.txt /tmp/hermes-cleanup/genuine-added.txt | sort > /tmp/hermes-cleanup/expected.txt
diff /tmp/hermes-cleanup/after.txt /tmp/hermes-cleanup/expected.txt && echo "TREE MATCHES EXPECTED"
```

Expected: `TREE MATCHES EXPECTED` — exactly 33 files differ from `v2026.7.20`, and they are precisely the genuine ones.

- [ ] **Step 11: Run the test suite to confirm cleanup broke nothing**

```bash
cd /e/GITHUB/projects/hermes-agent
python -m pytest tests/gateway tests/tools -x -q 2>&1 | tail -20
```

Record the exact pass/fail counts in the task output. If tests fail, run the same command at the `pre-v0.20.6-snapshot` tag to establish a baseline before assuming the cleanup caused it.

- [ ] **Step 12: Commit and push**

```bash
cd /e/GITHUB/projects/hermes-agent
git commit -m "fix: remove duplicated definitions from gateway, agent_init, telegram adapter

gateway/run.py spawned _async_delegation_watcher and _drain_control_watcher
twice (supervised + a resurrected bare create_task), so every gateway ran two
watchers double-draining the async-delegation queue since 2026-07-27. Also
drops 4 other duplicated methods, a duplicate platform_hints block upstream
already ships, and 2 duplicate Telegram adapter methods.

Genuine local patches preserved: Windows OSError fix, MISSION_CONTROL_SESSION_ID,
paper-digest callbacks."
git push origin main
```

---

## Task 6: Merge upstream v2026.8.27

**Files:**
- Modify: whatever the merge touches (conflicts expected only in the 10 genuine-modified files)

**Interfaces:**
- Consumes: the cleaned tree from Task 5.
- Produces: a genuine 2-parent merge commit, preserving merge-base tracking for the NEXT upgrade.

- [ ] **Step 1: Re-assert the merge-base immediately before merging**

```bash
cd /e/GITHUB/projects/hermes-agent
git merge-base HEAD v2026.8.27
```

Expected: `3ef6bbd201263d354fd83ec55b3c306ded2eb72a`.

- [ ] **Step 2: Run the merge in the background (it will exceed the 2-minute tool timeout)**

Use `run_in_background: true`:

```bash
cd /e/GITHUB/projects/hermes-agent && git merge v2026.8.27 --no-edit > /tmp/hermes-cleanup/merge.log 2>&1; echo "EXIT=$?" >> /tmp/hermes-cleanup/merge.log
```

If the merge is killed mid-flight, finish it manually:

```bash
cd /e/GITHUB/projects/hermes-agent
rm -f .git/index.lock
git add -A
git commit -m "merge: upstream v2026.8.27 (Hermes v0.19.0 -> v0.20.6)"
```

- [ ] **Step 3: Enumerate conflicts and check they are all expected**

```bash
cd /e/GITHUB/projects/hermes-agent
git status --short | grep -E "^(UU|AA|DU|UD|UA|AU|DD)" | tee /tmp/hermes-cleanup/conflicts.txt | wc -l
cut -c4- /tmp/hermes-cleanup/conflicts.txt | sort > /tmp/hermes-cleanup/conflicted-paths.txt
comm -23 /tmp/hermes-cleanup/conflicted-paths.txt /tmp/hermes-cleanup/genuine-mod.txt
```

The `comm` output lists paths that conflict but are NOT known local patches. Expected: empty or very short.
If it is large (dozens or more), the squash-merge failure mode has recurred — bulk-resolve provably-identical files with `git checkout --theirs --pathspec-from-file=<list>` (never `grep -Ff`) rather than resolving by hand.

- [ ] **Step 4: Resolve each conflict, preserving the genuine patch**

The rule for every file: **take upstream's structure, re-apply our patch on top.** Each file's patch is in the File Classification Reference table. Resolve one file at a time and `git add` it.

- `Dockerfile` — keep `--extra honcho` on upstream's `uv sync` line; upstream may have added other extras, keep theirs AND ours.
- `docker/stage2-hook.sh` — keep upstream's content AND our trailing `chmod 666 /var/run/docker.sock` block.
- `.gitignore`, `web/package.json` — keep both sides' additions.
- `gateway/run.py`, `tools/environments/base.py`, `hermes_cli/profiles.py`, `agent/agent_init.py`, `agent/conversation_loop.py`, `plugins/platforms/telegram/adapter.py` — take upstream, re-apply our patch.

- [ ] **Step 5: Verify every genuine patch survived**

```bash
cd /e/GITHUB/projects/hermes-agent
echo -n "profiles fallback:    "; grep -c "native.is_dir()" hermes_cli/profiles.py
echo -n "windows drain:        "; grep -c 'sys.platform == "win32"' tools/environments/base.py
echo -n "run.py windows fix:   "; grep -c "invalid PID on Windows" gateway/run.py
echo -n "paper-digest:         "; grep -ciE "paper.digest|paper_digest" plugins/platforms/telegram/adapter.py
echo -n "docker.sock chmod:    "; grep -c "chmod 666" docker/stage2-hook.sh
echo -n "honcho extra:         "; grep -c "extra honcho" Dockerfile
echo -n "MC session id:        "; grep -c "MISSION_CONTROL_SESSION_ID" agent/agent_init.py
echo -n "MC report_usage:      "; grep -c "report_usage" agent/conversation_loop.py
echo -n "sync-assets:          "; grep -c "sync-assets" web/package.json
echo -n "gitignore agents env: "; grep -c "agents/\*.env" .gitignore
```

Every count must be at least `1`. A `0` means that patch was lost during resolution — restore it before committing.

- [ ] **Step 6: Verify no duplication was reintroduced**

```bash
cd /e/GITHUB/projects/hermes-agent
for d in _async_delegation_watcher _enrich_async_delegation_routing _restore_moa_one_shot; do
  echo -n "$d (expect 1): "; grep -cE "^    (async )?def $d\b" gateway/run.py
done
echo -n "bare create_task spawns (expect 0): "
grep -cE "asyncio\.create_task\(self\._(async_delegation|drain_control)_watcher" gateway/run.py
```

- [ ] **Step 7: Confirm the merge commit has two parents**

```bash
cd /e/GITHUB/projects/hermes-agent
git commit --no-edit 2>/dev/null || true
git cat-file -p HEAD | head -4
git log --oneline -1
```

Expected: **two** `parent` lines. This is the check whose absence caused the v0.19.0 blowup — do not skip it.

- [ ] **Step 8: Smoke-test and push**

```bash
cd /e/GITHUB/projects/hermes-agent
python -c "import hermes_cli.config, hermes_cli.profiles, gateway.run; print('imports OK')"
python -m pytest tests/gateway tests/tools -x -q 2>&1 | tail -15
git push origin main
```

---

## Task 7: Fix known upstream breakages

**Files:**
- Modify: `pyproject.toml` (conditional)

**Interfaces:**
- Consumes: merged tree from Task 6.

- [ ] **Step 1: Check the `exclude-newer` trap**

Upstream has previously shipped a relative string here, which makes `uv` refuse to parse `pyproject.toml`, breaking every package install and causing "python-telegram-bot not installed" for pilot.

```bash
cd /e/GITHUB/projects/hermes-agent
grep -n "exclude-newer" pyproject.toml || echo "not present — nothing to fix"
```

If present with a relative value such as `"7 days"`, delete the line. An ISO datetime value is valid — leave it alone.

```bash
sed -i '/^exclude-newer = /d' pyproject.toml
```

- [ ] **Step 2: Verify uv can resolve the project**

```bash
cd /e/GITHUB/projects/hermes-agent
uv sync --extra messaging 2>&1 | tail -15
uv run python -c "import telegram; print('telegram', telegram.__version__)"
```

Expected: sync completes and telegram imports. This is the dependency pilot needs.

- [ ] **Step 3: Commit if changed**

```bash
cd /e/GITHUB/projects/hermes-agent
git diff --quiet pyproject.toml || { git commit -am "fix: drop invalid relative exclude-newer from pyproject.toml"; git push origin main; }
```

---

## Task 8: Raise the profile configs over the migration floor

**Files:**
- Modify: `C:\Users\Plamen\.hermes\profiles\{forge,pilot,reviewer,scout}\config.yaml`

**Interfaces:**
- Consumes: the effective-config baseline from Task 1 Step 5.
- Produces: four profile configs migrated from v10 to the current default (39), with behavior confirmed unchanged.

- [ ] **Step 1: Record the current state**

```bash
for p in default forge pilot reviewer scout; do
  f="C:/Users/Plamen/.hermes/profiles/$p/config.yaml"
  [ -f "$f" ] && echo "$p: $(grep -m1 '_config_version' "$f" || echo 'none')"
done
echo -n "root: "; grep -m1 '_config_version' "C:/Users/Plamen/.hermes/config.yaml"
```

Expected: forge/pilot/reviewer/scout at `10`; root config at `33`.

- [ ] **Step 2: Back up the four profile configs**

```bash
mkdir -p /tmp/hermes-cleanup/profile-configs
for p in forge pilot reviewer scout; do
  cp "C:/Users/Plamen/.hermes/profiles/$p/config.yaml" "/tmp/hermes-cleanup/profile-configs/$p.config.yaml"
done
ls -la /tmp/hermes-cleanup/profile-configs/
```

- [ ] **Step 3: Bump each to the floor version**

Upstream's own remedy message prescribes exactly this: set `_config_version: 12`, then let the normal ladder migrate 12 → 39.

```bash
for p in forge pilot reviewer scout; do
  f="C:/Users/Plamen/.hermes/profiles/$p/config.yaml"
  sed -i 's/^_config_version: 10$/_config_version: 12/' "$f"
  echo "$p -> $(grep -m1 '_config_version' "$f")"
done
```

Expected: all four report `_config_version: 12`.

- [ ] **Step 4: Trigger migration and confirm the floor warning is gone**

```bash
for p in forge pilot reviewer scout; do
  echo "=== $p"
  hermes -p "$p" config show > "/tmp/hermes-cleanup/$p.post.yaml" 2>"/tmp/hermes-cleanup/$p.err"
  grep -i "predates version\|can no longer be auto-migrated" "/tmp/hermes-cleanup/$p.err" \
    && echo "  FLOOR WARNING STILL PRESENT" || echo "  no floor warning"
  grep -m1 '_config_version' "C:/Users/Plamen/.hermes/profiles/$p/config.yaml"
done
```

Expected: no floor warning for any profile, and each `_config_version` now reads `39`.

- [ ] **Step 5: Diff effective config before vs after**

The migration must not silently change model, tools, or sandbox image.

```bash
for p in forge pilot reviewer scout; do
  echo "########## $p"
  diff "/tmp/hermes-preupgrade/$p.yaml" "/tmp/hermes-cleanup/$p.post.yaml" | head -40
done
```

Additive new-key defaults are expected. **Investigate any change to `model`, `docker_image`, `tools`, `memory.provider`, or `sandbox`** — those are the settings this deployment depends on. Record the reviewed diffs in the task output.

- [ ] **Step 6: Assert the settings that matter are unchanged**

```bash
for p in forge pilot reviewer scout; do
  echo -n "$p model: "; grep -m1 -E "^\s*model:" "/tmp/hermes-cleanup/$p.post.yaml"
  echo -n "$p image: "; grep -m1 -E "docker_image" "/tmp/hermes-cleanup/$p.post.yaml" || echo "(none)"
done
```

Compare against the pre-upgrade values: forge `kimi-k2.6:cloud`, reviewer `kimi-k2.5:cloud`, scout `glm-5:cloud`, pilot `glm-5.1:cloud`. Pilot and research must still use `hermes-sandbox:rtk-google`.

---

## Task 9: Rebuild the Docker images

**Files:**
- Build inputs: `Dockerfile`, `docker/Dockerfile.sandbox`, `docker/Dockerfile.sandbox.research`, `docker/stage2-hook.sh`, `docker/entrypoint.sh`

**Interfaces:**
- Consumes: merged tree from Task 6.
- Produces: rebuilt `hermes-agent`, `hermes-sandbox:rtk`, `hermes-sandbox:rtk-google`.

- [ ] **Step 1: Normalize shell-script line endings BEFORE building**

Any Windows edit to these introduces CRLF, which makes Linux fail the shebang with a confusing "no such file or directory".

```bash
cd /e/GITHUB/projects/hermes-agent
python - <<'PY'
for p in ("docker/entrypoint.sh", "docker/stage2-hook.sh"):
    data = open(p, "rb").read()
    n = data.count(b"\r\n")
    if n:
        open(p, "wb").write(data.replace(b"\r\n", b"\n"))
    print(f"{p}: fixed {n} CRLF endings")
PY
file docker/entrypoint.sh docker/stage2-hook.sh
```

Expected: `LF line terminators` for both, never `CRLF`.

- [ ] **Step 2: Commit any line-ending fix**

```bash
cd /e/GITHUB/projects/hermes-agent
git diff --quiet docker/ || { git commit -am "fix: normalize CRLF to LF in docker shell scripts"; git push origin main; }
```

- [ ] **Step 3: Build the main image (background — exceeds the tool timeout)**

Use `run_in_background: true`:

```bash
cd /e/GITHUB/projects/hermes-agent && docker build -t hermes-agent . > /tmp/hermes-cleanup/build-main.log 2>&1; echo "EXIT=$?" >> /tmp/hermes-cleanup/build-main.log
```

On completion:

```bash
tail -5 /tmp/hermes-cleanup/build-main.log
docker images --format '{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}' | grep hermes-agent
```

Expected: `EXIT=0` and a fresh timestamp.

- [ ] **Step 4: Verify honcho was baked into the image**

This is the whole reason for the `Dockerfile` local patch — if it silently dropped in the merge, memory providers break at runtime, not build time.

```bash
docker run --rm hermes-agent python -c "import honcho_ai; print('honcho OK')" 2>&1 | tail -3
```

Expected: `honcho OK`. If it fails, the `--extra honcho` patch did not survive Task 6 — fix it and rebuild.

- [ ] **Step 5: Build the sandbox images (background)**

`:rtk-google` derives `FROM hermes-sandbox:rtk`, so it MUST be built after `:rtk` or research and pilot stay on a stale base layer.

```bash
cd /e/GITHUB/projects/hermes-agent && docker build -f docker/Dockerfile.sandbox -t hermes-sandbox:rtk . > /tmp/hermes-cleanup/build-sandbox.log 2>&1 && docker build -f docker/Dockerfile.sandbox.research -t hermes-sandbox:rtk-google . > /tmp/hermes-cleanup/build-google.log 2>&1; echo "EXIT=$?" >> /tmp/hermes-cleanup/build-google.log
```

- [ ] **Step 6: Verify both sandbox images**

```bash
docker images --format '{{.Repository}}:{{.Tag}}\t{{.CreatedAt}}' | grep hermes-sandbox
docker run --rm hermes-sandbox:rtk-google python -c "import googleapiclient; print('google libs OK')" 2>&1 | tail -2
docker run --rm hermes-sandbox:rtk-google docker --version 2>&1 | tail -1
```

Expected: both images freshly dated; google libs import; Docker CLI present.

---

## Task 10: Update the host-native install

**Files:**
- Modify: `C:\Users\Plamen\.hermes\hermes-agent` (git pull via `hermes update`)

**Interfaces:**
- Consumes: the pushed fork `main` from Tasks 6–9.

- [ ] **Step 1: Confirm no gateway process is running**

Backend-refresh warnings during an update are caused by partially-loaded bytecode from a live process.

```bash
tasklist | grep -i "hermes" || echo "no hermes processes"
```

If any are running, stop them first (`hermes -p <profile> gateway stop`).

- [ ] **Step 2: Note the pre-existing dirty file**

The host-native repo carries a modified `package-lock.json`, a known consequence of the `web/package.json` `shx` patch. `hermes update` autostashes it.

```bash
git -C "C:/Users/Plamen/.hermes/hermes-agent" status --short
```

- [ ] **Step 3: Run the update (background — it is slow)**

```bash
hermes update > /tmp/hermes-cleanup/hermes-update.log 2>&1; echo "EXIT=$?" >> /tmp/hermes-cleanup/hermes-update.log
```

`website/tsconfig.json` conflicting on the stash pop is benign and expected.

Known failure mode: `npm ci` can fail `EUSAGE` because the root `package-lock.json` lacks `shx`. The updater falls back to `npm install` later in the same run and still completes. Treat a non-zero exit as real only if the version check in Step 4 fails.

- [ ] **Step 4: Verify the version**

```bash
hermes --version
git -C "C:/Users/Plamen/.hermes/hermes-agent" log --oneline -1
```

Expected: `Hermes Agent v0.20.6 (2026.8.27)`, with HEAD matching the fork's merge commit.

- [ ] **Step 5: Verify profiles still resolve**

```bash
hermes profile list
```

Expected: `default`, `forge`, `pilot`, `reviewer`, `scout` all present. A missing profile means the `hermes_cli/profiles.py` fallback patch was lost — re-check Task 6 Step 5.

---

## Task 11: Redeploy the containerized agents

**Files:**
- Modify: none — container lifecycle only. Compose file: `compose.hermes.local.yml`.

**Interfaces:**
- Consumes: images from Task 9.

- [ ] **Step 1: Recreate the agent containers**

```bash
cd /e/GITHUB/projects/hermes-agent
docker compose -f compose.hermes.local.yml up -d --force-recreate 2>&1 | tail -20
```

- [ ] **Step 2: Retire stale sandbox containers so they respawn on the new images**

```bash
for img in hermes-sandbox:rtk hermes-sandbox:rtk-google; do
  OLD=$(docker ps -aq --filter ancestor=$img)
  [ -n "$OLD" ] && docker rm -f $OLD || echo "none for $img"
done
```

- [ ] **Step 3: Check for the stale-lock failure mode**

`--force-recreate` has previously left root-owned lock files in `/opt/data` that make the gateway crash with `PermissionError`.

```bash
cd /e/GITHUB/projects/hermes-agent
docker compose -f compose.hermes.local.yml ps
for c in hermes hermes-agent-forge-1 hermes-agent-reviewer-1 hermes-agent-research-1; do
  echo "=== $c"; docker logs --tail 20 "$c" 2>&1 | grep -i "permissionerror\|locked\|traceback" || echo "  clean"
done
```

If `PermissionError` appears, fix ownership as root and restart that container:

```bash
docker exec -u root <container> chown -R hermes:hermes /opt/data
docker restart <container>
```

- [ ] **Step 4: Check for the duplicate-gateway reconciler bug**

The boot reconciler has twice resurrected stale `.hermes` profiles inside the main and dashboard containers.

```bash
for c in hermes hermes-dashboard; do
  echo "=== $c"; docker exec "$c" ps aux 2>/dev/null | grep "gateway run" | grep -v grep || echo "  no gateway processes"
done
```

No container should be running a gateway for a profile it does not own. If one is, stop it and set that profile's `gateway_state.json` to `{"gateway_state":"stopped","desired_state":"stopped"}`.

- [ ] **Step 5: Verify the team-plans permission gotcha has not returned**

Forge's root sandbox can write `600` root-owned files into `/workspace/.team/`, which reviewer (UID 10000) then cannot read.

```bash
docker exec hermes-agent-forge-1 ls -la /workspace/.team/ 2>&1 | head -10
```

If files are root-owned and unreadable:

```bash
docker exec -u root hermes-agent-forge-1 chmod -R a+rX /workspace/.team/
```

- [ ] **Step 6: Confirm all containers are healthy**

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}' | grep -E "hermes|honcho"
```

Expected: forge, reviewer, research report `(healthy)`; `hermes` and `hermes-dashboard` up.

---

## Task 12: Resolve the pilot placement anomaly

**Files:**
- Modify: `C:\Users\Plamen\.hermes\profiles\pilot\gateway_state.json` (conditional)

**Interfaces:**
- Produces: pilot running in exactly one place, matching the documented design.

**Context:** Before this upgrade, pilot's `gateway_state.json` showed PID 171 with argv `/opt/hermes/.venv/bin/hermes` — a *container* path — while no host `hermes.exe` process existed. Memory documents pilot as host-native. This is a pre-existing anomaly, not something this upgrade caused.

- [ ] **Step 1: Determine where pilot is actually running now**

```bash
cat "C:/Users/Plamen/.hermes/profiles/pilot/gateway_state.json"
echo "--- host processes ---"; tasklist | grep -i hermes || echo "none on host"
echo "--- in containers ---"
for c in hermes hermes-dashboard; do
  echo "=== $c"; docker exec "$c" ps aux 2>/dev/null | grep pilot | grep -v grep || echo "  no pilot"
done
```

- [ ] **Step 2: Report findings and confirm intent with the user**

Do NOT silently move pilot. Present what was found and ask whether pilot should be host-native (as memory documents) or is deliberately containerized now. Pilot holds Google OAuth credentials and a Telegram token; moving it has real consequences.

- [ ] **Step 3: If host-native is confirmed — stop the container instance**

```bash
docker exec hermes hermes -p pilot gateway stop 2>&1 | tail -5
cat > "C:/Users/Plamen/.hermes/profiles/pilot/gateway_state.json" <<'EOF'
{ "gateway_state": "stopped", "desired_state": "stopped" }
EOF
```

- [ ] **Step 4: Start pilot host-native and verify Telegram connects**

```bash
hermes -p pilot gateway start 2>&1 | tail -10
```

Wait ~15 seconds, then:

```bash
cat "C:/Users/Plamen/.hermes/profiles/pilot/gateway_state.json"
```

Expected: argv shows a Windows path (not `/opt/hermes/...`), and `platforms.telegram.state` is `connected`.

- [ ] **Step 5: Verify the watchdog can detect the process**

The watchdog filter was broken for two months because it matched `python.exe`/`python3.exe` while pilot runs as `hermes.exe`.

```bash
find /c/Users/Plamen -name "pilot-watchdog.ps1" -maxdepth 4 2>/dev/null
grep -n "hermes.exe" "C:/Users/Plamen/.hermes/pilot-watchdog.ps1" 2>/dev/null || echo "hermes.exe NOT in filter"
```

Expected: the filter alternation includes `hermes.exe`. If not, add it — otherwise the watchdog silently no-ops.

---

## Task 13: End-to-end verification and memory update

**Files:**
- Create: `C:\Users\Plamen\.claude\projects\E--GITHUB-projects\memory\hermes-v0206-upgrade.md`
- Modify: `memory\MEMORY.md`, `memory\hermes-post-update-checklist.md`

- [ ] **Step 1: Verify versions agree everywhere**

```bash
hermes --version
docker exec hermes hermes --version 2>&1 | head -2
git -C /e/GITHUB/projects/hermes-agent log --oneline -1
git -C /e/GITHUB/projects/hermes-agent describe --tags --abbrev=0
```

Expected: `v0.20.6 (2026.8.27)` from both host and container; describe reports `v2026.8.27`.

- [ ] **Step 2: Confirm the double-watcher fix reached the deployed image**

Checking the repo is not enough — verify inside a running container.

```bash
docker exec hermes-agent-forge-1 python -c "
import re, io
s = io.open('/opt/hermes/gateway/run.py', encoding='utf-8').read()
for n in ('_async_delegation_watcher','_drain_control_watcher'):
    print(n, 'defs=', len(re.findall(rf'^    (?:async )?def {n}\b', s, re.M)),
          'create_task=', len(re.findall(rf'asyncio\.create_task\(self\.{n}', s)))
" 2>&1 | tail -5
```

Expected: `defs= 1` and `create_task= 0` for both.

- [ ] **Step 3: Live-test each agent through Telegram**

Send a message to each agent's Telegram bot and confirm a reply. This is the only check that exercises the whole path — model routing, sandbox, memory provider, and the adapter's paper-digest callbacks.

Record which agents were tested and their responses. If an agent does not reply, check `docker logs --tail 50 <container>` before declaring the upgrade done.

- [ ] **Step 4: Verify memory providers still work**

```bash
docker exec hermes-agent-forge-1 hermes honcho status 2>&1 | tail -5
docker ps --format '{{.Names}}\t{{.Status}}' | grep honcho
```

Expected: honcho reports installed (not "honcho-ai is not installed"), and its containers are healthy.

- [ ] **Step 5: Write the upgrade memory**

Create `hermes-v0206-upgrade.md` with `type: project`. It must record:

- Source/target tags, and that the merge-base was verified intact (contrast with v0.19.0).
- **The duplication damage found and fixed** — 71 resurrected files, 26 artifact-modified files, and the double-spawned gateway watchers that ran in production from 2026-07-27 to 2026-08-31.
- **The generalizable lesson:** after any conflict-heavy merge, verify the *result* against the tag (`git diff --name-status <tag> HEAD`) rather than assuming resolution was correct. A merge that "completes" can still silently duplicate blocks and resurrect deleted files. Duplicated `def`s are invisible to Python, but double-spawned tasks are not.
- The config floor (`SUPPORT_FLOOR_VERSION = 12`) and that profile overlays sat at v10 while the root config was at v33.
- Rollback points: tag `pre-v0.20.6-snapshot-2026-08-31`, branch `pre-v0.20.6-snapshot`, backups at `E:\GITHUB\backups\hermes-pre-v0206-2026-08-31\`.
- Whatever was decided about pilot in Task 12.

- [ ] **Step 6: Update the checklist memory and the index**

Amend `hermes-post-update-checklist.md`: replace the stale "local patches as of v0.18.0" table with the verified 33-file classification from this upgrade, and add the post-merge duplication check (Task 6 Step 6) as a standing step.

Add one line to `MEMORY.md` under **Hermes Agent Setup**, newest first:

```markdown
- [v0.20.6 Upgrade (2026-08-31)](hermes-v0206-upgrade.md) — v0.19→v0.20.6 merge; found and fixed v0.19.0 merge damage (71 resurrected files, duplicated defs, double-spawned gateway watchers running since 2026-07-27); config floor v12 vs profile overlays at v10
```

- [ ] **Step 7: Final state check**

```bash
cd /e/GITHUB/projects/hermes-agent
git status --short
git log --oneline -8
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E "hermes|honcho"
```

Expected: clean tree, fork pushed, all agents up.
