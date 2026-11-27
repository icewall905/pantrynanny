import { describe, expect, it } from "vitest";
import type { RecipeSummary } from "../api/recipes";
import { matchesRecipe, pageOf } from "./recipeSearch";

const s = (
  title: string,
  tags: string[],
  ingredients: string[],
): RecipeSummary =>
  ({
    recipe: {
      id: title,
      title,
      description: null,
      source_name: null,
      course: "dinner",
      tags,
      ingredients: ingredients.map((name) => ({ name, raw: name })),
    },
    availability: { uses_expiring: ["Spinat"] },
  }) as unknown as RecipeSummary;

describe("matchesRecipe", () => {
  const r = s(
    "Pasta Carbonara",
    ["italiensk", "hurtig"],
    ["spaghetti", "æg", "bacon"],
  );
  it("matches title, tags, ingredients, course, expiring", () => {
    for (const q of [
      "carbo",
      "#hurtig",
      "ITALIENSK",
      "bacon",
      "dinner",
      "spinat",
      "",
      "  ",
    ])
      expect(matchesRecipe(r, q)).toBe(true);
  });
  it("needs every word", () => {
    expect(matchesRecipe(r, "pasta æg")).toBe(true);
    expect(matchesRecipe(r, "pasta kylling")).toBe(false);
  });
  it("ignores accents and uses extra labels", () => {
    expect(matchesRecipe(s("Crème brûlée", [], []), "creme brulee")).toBe(true);
    expect(matchesRecipe(r, "aftensmad", ["Aftensmad"])).toBe(true);
  });
});

describe("pageOf", () => {
  it("slices and clamps", () => {
    const xs = Array.from({ length: 50 }, (_, i) => i);
    expect(pageOf(xs, 0, 24)).toMatchObject({
      page: 0,
      pages: 3,
      items: xs.slice(0, 24),
    });
    expect(pageOf(xs, 9, 24)).toMatchObject({ page: 2, items: [48, 49] });
    expect(pageOf([], 3, 24)).toMatchObject({ page: 0, pages: 1, items: [] });
  });
});

describe('categories', () => {
  it('lists distinct categories and filters case-insensitively', async () => {
    const { categoriesOf, inCategory } = await import('./recipeSearch')
    const a = s('A', [], [])
    const b = s('B', [], [])
    a.recipe.categories = ['Dinner', 'Lunch']
    b.recipe.categories = ['dinner', 'Dessert']
    expect(categoriesOf([a, b])).toEqual(['Dessert', 'Dinner', 'Lunch'])
    expect(inCategory(b, 'DINNER')).toBe(true)
    expect(inCategory(a, 'Dessert')).toBe(false)
    expect(inCategory(a, null)).toBe(true)
    expect(matchesRecipe(a, 'lunch')).toBe(true)
  })
})
