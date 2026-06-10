# Hermes v0.15.2 → v0.16.0 Upgrade Plan

**Date:** 2026-06-10  
**Target:** upstream tag `v2026.6.5` ("The Surface Release")  
**Approach:** git merge (NOT `hermes update`) — same path as the v0.13.0→v0.15.2 upgrade  
**Rollback:** `git checkout pre-v0.16.0-snapshot-2026-06-10` + restore hermes-data from robocopy backup

---

## Phase 0 — Snapshot (safety net, ~5 min)

```powershell
# 1. Snapshot git state
cd E:\GITHUB\projects\hermes-agent
git tag pre-v0.16.0-snapshot-2026-06-10
git bundle create E:\GITHUB\backups\hermes-pre-v016-2026-06-10\hermes-agent.bundle --all

# 2. Back up live data volumes
robocopy E:\GITHUB\projects\hermes-data E:\GITHUB\backups\hermes-pre-v016-2026-06-10\hermes-data /E /COPYALL /R:1

# 3. Back up ~/.hermes (pilot config, profiles, secrets)
Compress-Archive -Path C:\Users\Plamen\.hermes -DestinationPath E:\GITHUB\backups\hermes-pre-v016-2026-06-10\dot-hermes.zip
```

---

## Phase 1 — Stop all agents (~2 min)

```powershell
# Stop pilot watchdog first (otherwise it auto-restarts pilot during upgrade)
schtasks /End /TN HermesPilotWatchdog

# Kill pilot gateway
Get-Process -Name "python*" | Where-Object { $_.CommandLine -like "*pilot*" } | Stop-Process -Force
# Or if running in terminal: Ctrl+C in that window

# Stop Docker agents
cd E:\GITHUB\projects\hermes-agent
docker compose -f docker-compose.yml -f compose.hermes.local.yml down
```

Confirm: `docker ps` should show no hermes-agent containers.

---

## Phase 2 — Git merge (~10 min, including conflict resolution)

```bash
cd E:/GITHUB/projects/hermes-agent

# Fetch upstream
git fetch upstream --tags

# Merge v0.16.0 tag
git merge v2026.6.5 --no-edit
```

### Expected conflict sites

| File | Expected conflict | Resolution |
|------|------------------|------------|
| `tools/environments/base.py` | `_drain()` — Windows select fix (Patch 2) | Keep **our** `sys.platform == "win32"` branch; take upstream's surrounding changes |
| `docker/stage2-hook.sh` | docker.sock chmod block (Patch 3) | Keep **both** — upstream init lines + our `chmod 666 /var/run/docker.sock` block |
| `gateway/platforms/telegram.py` | Paper-digest callbacks | Keep **our** changes; take upstream's surrounding changes |
| `hermes_cli/profiles.py` | Profiles fallback patch | Keep **our** fallback; take upstream's surrounding changes |
| `web/package-lock.json` | Always conflicts | `git checkout --theirs web/package-lock.json` |
| `pyproject.toml` | `exclude-newer` string | Remove the line if it's a relative string like `"7 days"` |

After resolving each conflict, check for fragments:

```bash
grep -n "<<<<<<\|>>>>>>>\|=======" tools/environments/base.py docker/stage2-hook.sh gateway/platforms/telegram.py hermes_cli/profiles.py
python -c "import tools.environments.base; import hermes_cli.profiles" && echo "syntax OK"
```

Complete the merge:
```bash
git add -A
git commit
```

---

## Phase 3 — Verify all local patches survived (~5 min)

```bash
# Patch 2 — Windows select() drain
grep -n "^import sys" tools/environments/base.py
grep -n 'sys.platform == "win32"' tools/environments/base.py

# Patch 3 — docker.sock chmod in stage2-hook
grep -n "docker.sock" docker/stage2-hook.sh

# Profiles fallback
grep -n "fallback\|native.*is_dir\|computed.*is_dir" hermes_cli/profiles.py

# Telegram paper-digest
grep -n "paper-digest\|update_prompt" gateway/platforms/telegram.py | head -5

# MC reporter thread safety
grep -n "threading.local" mission_control_reporter.py

# pyproject.toml — no relative exclude-newer
grep "exclude-newer" pyproject.toml  # must return nothing, or an ISO date, not "7 days"
```

If any patch is missing, reapply from memory (see hermes-windows-patches.md, hermes-post-update-checklist.md).

---

## Phase 4 — Check v0.16.0-specific changes (~10 min)

**4a. "Leaner default skill set" — check team skills survived**
```bash
ls hermes-agent/skills/
ls E:/GITHUB/projects/hermes-gateway/workspace/.team/skills/  # volume-based, should be untouched
```

**4b. Validate compose schema hasn't broken local overrides**
```bash
docker compose -f docker-compose.yml -f compose.hermes.local.yml config --quiet
```
If this errors, the upstream `docker-compose.yml` schema changed — update `compose.hermes.local.yml` to match before proceeding.

**4c. Verify agent config `docker_image` values (resets to nikolaik every upgrade)**
```bash
grep -A1 "docker_image" agents/coding-config.yaml agents/research-config.yaml agents/reviewer-config.yaml
```
Expected:
- `coding-config.yaml` → `hermes-sandbox:rtk`
- `research-config.yaml` → `hermes-sandbox:rtk-google`
- `reviewer-config.yaml` → *(no docker_image entry)*

If reverted to `nikolaik`, fix BOTH files:
- `agents/<name>-config.yaml` (baked into image)
- `hermes-data/<name>/config.yaml` (live volume)

**4d. Fix CRLF in shell scripts**
```bash
python -c "
for f in ['docker/entrypoint.sh','docker/stage2-hook.sh']:
    data = open(f,'rb').read()
    crlf = data.count(b'\r\n')
    print(f'{f}: {crlf} CRLF endings')
    if crlf:
        open(f,'wb').write(data.replace(b'\r\n',b'\n'))
        print(f'  Fixed.')
"
```

---

## Phase 5 — Rebuild images (~20–40 min)

```bash
cd E:/GITHUB/projects/hermes-agent

# 1. Main hermes-agent image
docker compose build gateway

# 2. Base sandbox (rtk)
docker build -f docker/Dockerfile.sandbox -t hermes-sandbox:rtk .

# 3. Derived sandbox (rtk-google — used by research AND pilot's sandbox)
docker build -f docker/Dockerfile.sandbox.research -t hermes-sandbox:rtk-google .

# Remove stale sandbox containers
docker rm -f $(docker ps -aq --filter ancestor=hermes-sandbox:rtk) 2>/dev/null
docker rm -f $(docker ps -aq --filter ancestor=hermes-sandbox:rtk-google) 2>/dev/null
```

---

## Phase 6 — Start agents in sequence (~10 min)

```bash
# Preempt stale-lock PermissionErrors (chown /opt/data before recreating)
docker run --rm -v E:/GITHUB/projects/hermes-data/coding:/data alpine sh -c "chown -R 10000:10000 /data"
docker run --rm -v E:/GITHUB/projects/hermes-data/research:/data alpine sh -c "chown -R 10000:10000 /data"
docker run --rm -v E:/GITHUB/projects/hermes-data/reviewer:/data alpine sh -c "chown -R 10000:10000 /data"

# Start Docker agents
HERMES_UID=$(id -u) HERMES_GID=$(id -g) \
  docker compose -f docker-compose.yml -f compose.hermes.local.yml up -d
```

Wait ~2–3 min for cont-init (s6 chown on Windows volume mounts is slow). Use process check — NOT healthcheck (healthcheck passes before hermes is ready):
```bash
docker exec hermes-agent-forge-1 sh -c "ps -ef | grep 'hermes gateway run'"
docker exec hermes-agent-research-1 sh -c "ps -ef | grep 'hermes gateway run'"
docker exec hermes-agent-reviewer-1 sh -c "ps -ef | grep 'hermes gateway run'"
```

Then start pilot (host-native):
```powershell
hermes --profile pilot gateway run

# Re-enable watchdog
schtasks /Run /TN HermesPilotWatchdog
```

---

## Phase 7 — Verify (~5 min)

```powershell
hermes --version          # should show v0.16.0 / 2026.6.5
hermes profile list       # forge, reviewer, scout, pilot must appear
```

Send a test message to each Telegram bot. For pilot, check log (gateway status is unreliable on Windows):
```powershell
Get-Content C:\Users\Plamen\.hermes\profiles\pilot\logs\agent.log -Tail 20
```

Push the fork:
```bash
git push origin main
```

---

## Risk summary

| Risk | Mitigation |
|------|------------|
| "Leaner default skill set" wipes agent skills | Shared `.team/skills/` on volume — unaffected; agent-specific skills may need re-adding |
| Compose schema change breaks `compose.hermes.local.yml` | Phase 4b dry-run catches before any container starts |
| `docker_image` resets to nikolaik | Phase 4c grep catches it before rebuild |
| Patch 2 (Windows drain) lost | Phase 3 greps; pilot terminal silently breaks if missed |
| Patch 3 (docker.sock) lost | Phase 3 greps; forge/research lose Docker-in-Docker access |
| cont-init chown false-healthy | Phase 6 uses `ps -ef` not healthcheck |
| Stale lock files on force-recreate | Phase 6 alpine chown step preempts it |
| New v0.16.0 native desktop changes | Low risk for Docker/host-native setup — desktop app is opt-in |
