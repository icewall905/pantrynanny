# Importing recipes from Mealie

`pantrynanny-admin import-mealie` copies recipes from a [Mealie](https://mealie.io) server into a household,
with their **categories, tags, times and photos**. It is safe to run again: nothing is duplicated.

```bash
# in the PantryNanny container/host, as the service user
export PN_MEALIE_TOKEN=...        # Mealie → User profile → API tokens (or use --token-file / the prompt)
pantrynanny-admin import-mealie --url https://mealie.example.com
```

| Option | Meaning |
|---|---|
| `--url` | Mealie base URL (required). |
| `--token-file FILE` | Read the API token from a file instead of `PN_MEALIE_TOKEN` or the prompt. |
| `--household` | Household id or name, when there are several. |
| `--limit N` | Look at most N Mealie recipes (try it out first). |
| `--no-create` | Only update recipes that are already here (e.g. add photos/categories to an earlier import). |
| `--no-images` | Do not copy photos. |
| `--replace-images` | Copy Mealie's photo again even when the recipe already has a stored one. |

## What happens per Mealie recipe

- **Already here?** Matched by the Mealie id stored by an earlier run (`external_id`), else the same source URL,
  else the same title. Such a recipe gets Mealie's categories, any tags it lacks, cooking times and course when
  they are empty, and the photo when it has no stored one. Its ingredients, steps and anything typed in PantryNanny
  are left alone.
- **New:** created from the full Mealie recipe (ingredient lines, steps, servings, times, tags, categories, source
  link). The course comes from the categories (Breakfast, Lunch, Dinner, Dessert, Drinks …) or the usual guess.
- **Photos** are downloaded from Mealie with the token, re-encoded to WebP (metadata stripped) and stored in
  `PN_UPLOAD_DIR` like product photos, so they show in the web app and on the phone even where Mealie is not
  reachable.

The web app and the Android app show the photos on the recipe cards and let you pick a category on
"What can we cook?" and "All recipes".

## Recipes that arrived with "Could not detect instructions"

Mealie stores the sentence *"Could not detect instructions"* / *"Could not detect ingredients"* when its
scraper gives up, and the import copies what Mealie has. Such a recipe shows a title, a photo and one
meaningless line. `pantrynanny-admin repair-recipes` reads its source page again and replaces **only** the
ingredient list and the steps; the title, photo, times, tags and course stay as they are.

```bash
pantrynanny-admin repair-recipes --dry-run      # read the pages, change nothing, list what it would fill
pantrynanny-admin repair-recipes                # fill in what the pages still hold as schema.org data
pantrynanny-admin repair-recipes --ai           # also read pages that have no schema.org data at all
pantrynanny-admin repair-recipes --overrides found.json   # {recipe id: url} for pages that are gone
```

`--ai` uses the household's own model (Admin → AI) to copy the ingredients and method off a page that has
no structured data. Every line it returns is checked against the page's own words and dropped when it is not
really there; an answer that is mostly not from the page is thrown away, so a recipe is never filled with
guessed content. A page that holds nothing (gone, no list, a video) leaves the recipe untouched and is
listed as a problem instead. `--json report.json` writes the whole run for later reading.

Find the recipe elsewhere and pass its link in the `--overrides` file when the original page is dead (404);
`--dry-run` first shows which recipes need that.
