---
name: albert-heijn
description: Albert Heijn grocery shopping integration for the Netherlands. Search products, check weekly bonus deals, manage shopping lists, discover Allerhande recipes, and track purchase history. Requires OAuth login via browser.
version: 1.0.0
author: community
license: AGPL-3.0
required_commands:
  - go
required_credential_files:
  - path: .appie.json
    description: Albert Heijn OAuth tokens (auto-created on login)
metadata:
  hermes:
    tags: [Albert Heijn, AH, grocery, shopping, Netherlands, Allerhande, recipes]
    homepage: https://github.com/markooms/openclaw-skill-albert-heijn
---

# Albert Heijn Grocery Skill

Weekly meal planning, recipe discovery, and grocery list management for Albert Heijn (Netherlands).

> **Disclaimer:** This is an unofficial, community-built integration. It is not affiliated with, endorsed by, or connected to Albert Heijn or Ahold Delhaize in any way. Uses the same mobile API that the Appie app uses — undocumented and may change without notice.

## Prerequisites

- Go 1.21+ installed
- Albert Heijn account (for authenticated features)

## First-Time Setup

### Step 1: Install Go (if not present)

```bash
go version
```

If not installed:
```bash
curl -L https://go.dev/dl/go1.23.6.linux-amd64.tar.gz -o /tmp/go.tar.gz
mkdir -p ~/.local
tar -C ~/.local -xzf /tmp/go.tar.gz
export PATH=$HOME/.local/go/bin:$HOME/go/bin:$PATH
```

Add to shell profile for persistence:
```bash
echo 'export PATH=$HOME/.local/go/bin:$HOME/go/bin:$PATH' >> ~/.bashrc
```

### Step 2: Build appie-cli

From this skill's directory:
```bash
cd ~/.hermes/optional-skills/albert-heijn/appie-cli
go build -o appie-cli .
mv appie-cli ~/go/bin/
```

Verify:
```bash
appie-cli search "kaas" 3
```

This returns product results (no login required for search).

### Step 3: User Login (requires human interaction)

**Easiest method: local login page**
```bash
appie-cli login
```

This starts a local web page. Send the URL (http://127.0.0.1:PORT) to the user. The page guides them through:
1. Click the login button to open AH login
2. Log in with their AH account
3. After the redirect fails (normal), paste the URL from address bar into the form

**Manual method (fallback for remote environments):**
```bash
appie-cli login-url
```

Send the URL to the user. After login, the browser redirects to `appie://login-exit?code=XXXXX`. The user copies the code:

```bash
appie-cli exchange-code XXXXX
```

Verify:
```bash
appie-cli member
```

Tokens are saved to `.appie.json` and auto-refresh. One-time setup.

### Step 4: Configure preferences

```bash
cp ~/.hermes/optional-skills/albert-heijn/config-template.json ~/.hermes/optional-skills/albert-heijn/config.json
```

**Ask the user:**
1. How many meals per week? How many people?
2. Max cooking time preference?
3. Dislikes or allergies?
4. Shopping day preference?
5. Any items bought elsewhere (butcher, bakery)?

### Step 5: Set up weekly basics

```bash
cp ~/.hermes/optional-skills/albert-heijn/weekly-basics-template.json ~/.hermes/optional-skills/albert-heijn/weekly-basics.json
```

Ask what they buy every week (milk, bread, eggs, fruit). Search for product IDs:
```bash
appie-cli search "halfvolle melk" 3
```

### Step 6: Show user their AH profile

```bash
appie-cli member
```

Returns AH's internal profile: age range, life stage, food profile, diet type, price segment, shopping habits. Share highlights with the user.

### Step 7: Build taste profile

Pull purchase history:
```bash
appie-cli previously-bought 100 0
appie-cli previously-bought 100 1
```

Create `taste-profile.md` from the template.

## Weekly Workflow

Run on the day before shopping day.

### 1. Gather Data

```bash
# Current bonus products
appie-cli bonus-products 200

# Purchase history for matching
appie-cli previously-bought 100 0
```

Read `weekly-basics.json` for recurring items.

### 2. Find Bonus Matches

Cross-reference bonus products with previously bought items (`isPreviouslyBought: true`). These are deals the user actually cares about.

### 3. Search Recipes

```bash
# Search by keyword
appie-cli search-recipes "pasta" 20

# Get full recipe
appie-cli recipe <recipe-id>
```

Filter by:
- Cooking time ≤ `max_cooking_time_minutes`
- No ingredients in `dislikes` or `allergies`
- Prefer recipes using current bonus ingredients

### 4. Present Proposal

Send meal suggestions via chat. Include:
- Recipe name + link + cooking time
- Which ingredients are on bonus 🏷️
- Butcher items 🥩
- Items needed beyond basics

**ALWAYS wait for user approval before touching shopping list.**

### 5. Handle Feedback

- Approve → add to shopping list
- Modify → adjust and ask again
- Reject → suggest alternatives

Log in `meal-history.json`.

### 6. Fill Shopping List

Check `product-cache.json` first to avoid repeated searches.

**Butcher check:** For each ingredient, check if it matches `butcher_items` in config. If yes, add as free text:
```bash
appie-cli add-to-list --text "🥩 Slager: kipfilet" 1
```

**Deduplication:** Combine ingredients across recipes. One package may cover multiple recipes.

**Batch add:**
```bash
echo '[{"id": 54074, "qty": 1}, {"id": 197393, "qty": 1}, {"text": "Slager: kipfilet", "qty": 1}]' | appie-cli batch-add
```

## API Reference

| Command | What it does | Auth |
|---------|--------------|------|
| `search <query> [limit]` | Search products | No |
| `product <id>` | Product details | No |
| `bonus-products [limit]` | Current deals | No |
| `previously-bought [size] [page]` | Purchase history | Yes |
| `shopping-list` | View list | Yes |
| `add-to-list <id> [qty]` | Add product | Yes |
| `add-to-list --text "item"` | Add free text | Yes |
| `batch-add` | Add multiple (stdin JSON) | Yes |
| `clear-list` | Clear list | Yes |
| `search-recipes [query] [limit]` | Search Allerhande | No |
| `recipe <id>` | Recipe details | No |
| `member` | Member profile | Yes |

## Files

- `config.json` — User preferences (copy from template)
- `weekly-basics.json` — Recurring grocery items
- `taste-profile.md` — Learned preferences
- `meal-history.json` — Meal approvals/rejections
- `product-cache.json` — Cached product IDs
- `.appie.json` — Auth tokens (auto-created, DO NOT commit)

## Important Rules

- **NEVER** add items without user approval
- **Butcher items:** Check EVERY meat/protein against `butcher_items`. If match, use free text.
- Respect dislikes and allergies
- Prefer bonus items in meal suggestions
- Keep recipes practical (common ingredients, within time limit)
- When in doubt, ask the user

## Known Issues

- `receipts` endpoint returns 503 error (upstream AH API issue). Use `previously-bought` instead.