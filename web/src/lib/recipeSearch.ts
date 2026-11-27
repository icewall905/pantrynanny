import type { RecipeSummary } from "../api/recipes";

const fold = (s: string) =>
  s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "");

/** Every word of the query must appear somewhere: title, tags, course, ingredients, description,
 * source or what it uses up. `#tag` is the same as `tag`. `extra` adds e.g. translated labels. */
export function matchesRecipe(
  s: RecipeSummary,
  query: string,
  extra: string[] = [],
): boolean {
  const words = fold(query)
    .split(/\s+/)
    .map((w) => w.replace(/^#/, ""))
    .filter(Boolean);
  if (words.length === 0) return true;
  const r = s.recipe;
  const hay = fold(
    [
      r.title,
      r.description ?? "",
      r.source_name ?? "",
      r.course ?? "",
      ...r.tags,
      ...(r.categories ?? []),
      ...r.ingredients.map((i) => i.name || i.raw),
      ...s.availability.uses_expiring,
      ...extra,
    ].join("\n"),
  );
  return words.every((w) => hay.includes(w));
}

/** Distinct categories of the loaded recipes, sorted. */
export function categoriesOf(list: RecipeSummary[]): string[] {
  const seen = new Map<string, string>()
  for (const s of list) for (const c of s.recipe.categories ?? []) if (!seen.has(c.toLowerCase())) seen.set(c.toLowerCase(), c)
  return [...seen.values()].sort((a, b) => a.localeCompare(b))
}

export const inCategory = (s: RecipeSummary, cat: string | null) =>
  !cat || (s.recipe.categories ?? []).some((c) => c.toLowerCase() === cat.toLowerCase())

/** Tagged anti-inflammatory (Mealie's "Anti-Inflammatory"; spelling and dashes do not matter). */
export const isAntiInflammatory = (s: RecipeSummary) =>
  s.recipe.tags.some((t) => fold(t).replace(/[^a-z]/g, '') === 'antiinflammatory' || fold(t).replace(/[^a-z]/g, '') === 'antiinflammatorisk')

export const PAGE_SIZE = 24;

/** Clamp `page` (0-based) and slice. */
export function pageOf<T>(items: T[], page: number, size = PAGE_SIZE) {
  const pages = Math.max(1, Math.ceil(items.length / size));
  const p = Math.min(Math.max(0, page), pages - 1);
  return { page: p, pages, items: items.slice(p * size, (p + 1) * size) };
}
