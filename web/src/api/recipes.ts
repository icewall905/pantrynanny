import type { ISODate, ISODateTime, UUID } from './types'

export interface Ingredient {
  id: UUID
  position: number
  raw: string
  name: string
  quantity: number | null
  unit: string | null
  note: string | null
  optional: boolean
  product_id: UUID | null
}
export interface Recipe {
  id: UUID
  version: number
  title: string
  description: string | null
  servings: number
  prep_min: number | null
  cook_min: number | null
  instructions: string[]
  tags: string[]
  source_url: string | null
  source_name: string | null
  image_url: string | null
  ingredients: Ingredient[]
  created_at: ISODateTime
  updated_at: ISODateTime
}
export type IngredientStatus = 'have' | 'low' | 'missing' | 'staple' | 'optional'
export interface IngredientAvailability {
  ingredient: Ingredient
  status: IngredientStatus
  product: { id: UUID; name: string; total_quantity: number; stock_unit: string; image_url: string | null; next_expiry: ISODate | null } | null
  linked: boolean
  need: number | null
  enough: boolean | null
  expiring: boolean
}
export interface Availability {
  recipe_id: UUID
  servings: number
  have: number
  missing: number
  required: number
  coverage: number
  uses_expiring: string[]
  items: IngredientAvailability[]
}
export interface RecipeSummary {
  recipe: Recipe
  availability: Availability
}
export interface RecipeDraft {
  title: string
  description: string | null
  servings: number | null
  prep_min: number | null
  cook_min: number | null
  ingredients: string[]
  instructions: string[]
  tags: string[]
  image_url: string | null
  source_url: string
  source_name: string | null
}
export interface RecipeInput {
  title: string
  description: string | null
  servings: number
  prep_min: number | null
  cook_min: number | null
  instructions: string[]
  tags: string[]
  source_url: string | null
  source_name: string | null
  image_url: string | null
  ingredients: { raw: string; product_id?: UUID | null }[]
}
export interface ParsedLine {
  raw: string
  name: string
  quantity: number | null
  unit: string | null
  note: string | null
  optional: boolean
}
export type Slot = 'breakfast' | 'lunch' | 'dinner' | 'snack'
export interface Meal {
  id: UUID
  day: ISODate
  slot: Slot
  recipe_id: UUID | null
  recipe_title: string | null
  title: string | null
  servings: number | null
  note: string | null
  cooked_at: ISODateTime | null
  missing: number | null
}

export const totalMinutes = (r: Pick<Recipe, 'prep_min' | 'cook_min'>) => (r.prep_min ?? 0) + (r.cook_min ?? 0)
