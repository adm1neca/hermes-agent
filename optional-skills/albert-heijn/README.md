# 🛒 OpenClaw Skill: Albert Heijn

> ⚠️ **Disclaimer:** This is an **unofficial, community-built** integration. It is not affiliated with, endorsed by, or connected to Albert Heijn or Ahold Delhaize in any way. It uses the same mobile API that the Appie app uses — this is undocumented and may change or break without notice. The login flow is hacky (you need to extract an auth code from browser DevTools). You may run into rate limits or blocked requests. **Use at your own risk.**

An [OpenClaw](https://github.com/openclaw/openclaw) skill that turns your AI assistant into a personal grocery planner for [Albert Heijn](https://ah.nl) — the largest supermarket chain in the Netherlands. Built on top of the excellent [appie-go](https://github.com/gwillem/appie-go) library by [@gwillem](https://github.com/gwillem).

> **Your agent analyzes what you buy, checks this week's deals, suggests meals, and fills your shopping list — all through chat.**

## What It Does

1. 🔐 **Login** — Authenticates with your AH account via OAuth
2. 📊 **Analyze** — Pulls your purchase history (previously bought products)
3. 🧠 **Learn** — Builds a taste profile from your history + feedback
4. 🏷️ **Bonus** — Checks weekly deals and matches them to your preferences
5. 🍽️ **Suggest** — Proposes meals using Allerhande recipes, optimized for bonus items
6. 🛒 **Shop** — Adds everything to your AH shopping list (basics + meal ingredients)
7. 📈 **Improve** — Learns from approvals/rejections to get better over time

## Quick Start

### 1. Install the CLI tool

Requires [Go 1.21+](https://go.dev/dl/):

```bash
cd appie-cli
go build -o appie-cli .
mv appie-cli ~/go/bin/  # or anywhere in your PATH
```

### 2. Login to Albert Heijn

```bash
appie-cli login-url
# Outputs a URL like: https://login.ah.nl/login?client_id=appie-ios&...
```

1. Open **Developer Tools** in your browser first (F12), go to the **Network** tab, and enable **Preserve log**
2. Open the URL and log in with your Albert Heijn account
3. After login, the browser will try to redirect to `appie://login-exit?code=XXXXX` — this will fail (it's a mobile app link, that's expected)
4. In the Network tab, find **`ingelogd.json`**
5. Click it and look at the **Response** — you'll see:
   ```json
   "pageProps": {
     "__N_REDIRECT": "appie://login-exit?code=XXXXX",
     "__N_REDIRECT_STATUS": 302
   }
   ```
6. Copy the code (everything after `code=`)

```bash
appie-cli exchange-code <your-code>
```

Tokens are saved to `.appie.json` and auto-refresh.

### 3. Configure the skill

```bash
cp config-template.json config.json
```

Edit `config.json` with your preferences:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `meals_per_week` | 3 | Number of meal suggestions per week |
| `max_cooking_time_minutes` | 30 | Max cooking time for recipes |
| `household_size` | 2 | Number of people |
| `shopping_day` | `"friday"` | When you do groceries |
| `proposal_day` | `"thursday"` | When to receive meal proposals |
| `dislikes` | `[]` | Ingredients to avoid (e.g. `["fish", "mushrooms"]`) |
| `allergies` | `[]` | Allergies (e.g. `["gluten", "lactose"]`) |
| `butcher_items` | `[]` | Items to buy at the butcher instead of AH (optional) |
| `preferences.healthy` | `true` | Prefer healthy recipes |
| `preferences.prefer_bonus` | `true` | Prefer ingredients that are on sale |

### 4. Point your OpenClaw agent at this skill

Add to your OpenClaw workspace and the agent will handle the rest through conversation.

## How It Works

### API Discovery

The skill uses the **Albert Heijn mobile API** (`api.ah.nl`) — the same API that powers the Appie app:

| Feature | Endpoint | Auth |
|---------|----------|------|
| Product search | REST `/mobile-services/product/search/v2` | Anonymous |
| Previously bought | GraphQL `productSearch(previouslyBought: true)` | Required |
| Bonus products | REST `?bonus=true` via AHWEBSHOP | Anonymous |
| Shopping lists | REST `/mobile-services/lists/v3/lists` | Required |
| Add to list | REST `PATCH /mobile-services/shoppinglist/v2/items` | Required |
| Recipes | GraphQL `recipeSearch` + `recipe(id)` | Anonymous |
| Member profile | GraphQL `member` | Required |

### API Notes

- **`previouslyBought: true`** in `ProductSearchInput` returns all products you've ever purchased — this is undocumented
- **`customerProfileAudiences`** on the member query reveals AH's internal segmentation (frequent buyer categories, food profile, dietary preferences)
- **Allerhande recipes** are fully queryable via GraphQL with ingredients, cooking times, and portions
- **Bonus products** need the `x-application: AHWEBSHOP` header to return results via REST

### Weekly Flow

```
Thursday morning (cron job):
  ├── Fetch favorite lists (weekly basics)
  ├── Fetch current bonus products
  ├── Match bonus with purchase history
  ├── Search Allerhande recipes matching:
  │   ├── Taste profile preferences
  │   ├── Available bonus ingredients
  │   ├── Cooking time constraints
  │   └── Dislike/allergy filters
  ├── Propose N meals via chat
  ├── Wait for approval/modifications
  └── Add all items to AH shopping list (via batch-add)
      ├── Look up product IDs from product-cache.json first
      ├── Weekly basics (from favorite lists)
      ├── Meal ingredients (with product IDs)
      ├── Butcher items (as free text notes)
      └── Cache any newly discovered product IDs
```

## CLI Reference

```
appie-cli <command> [args]

Auth:
  login-url                    Get the AH login URL
  exchange-code <code>         Exchange auth code for tokens

Products:
  search <query> [limit]       Search products
  product <id>                 Get product details
  bonus-products [limit]       Get current bonus products
  previously-bought [size] [page]  Get previously bought products

Shopping List:
  shopping-list                Show main shopping list
  shopping-lists               List all shopping lists
  list-items <list-id>         Get items in a specific list
  add-to-list <id> [qty]       Add product to shopping list
  add-to-list --text "item"    Add free text item
  batch-add                    Add multiple items from stdin (JSON array)
  clear-list                   Clear shopping list

Account:
  member                       Show member profile
  receipts                     List receipts (⚠️ currently broken, see Known Issues)
  receipt <id>                 Get receipt details (⚠️ currently broken)
```

## Credits

- **[appie-go](https://github.com/gwillem/appie-go)** by [@gwillem](https://github.com/gwillem) — the Go library that makes this possible

## License

AGPL-3.0 

## Known Issues

- **Receipts endpoint broken** — the AH receipt API returns 503. Tracked at [gwillem/appie-go#1](https://github.com/gwillem/appie-go/issues/1). Use `previously-bought` as an alternative.

## Disclaimer

This is an unofficial integration. Not affiliated with Albert Heijn or Ahold Delhaize. Use at your own risk. The API may change without notice.
