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
