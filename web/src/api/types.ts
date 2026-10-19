// Types mirroring docs/api-contract.md. Keep in sync with the backend schemas.

export type UUID = string
export type ISODate = string // YYYY-MM-DD
export type ISODateTime = string

export type Unit = 'pcs' | 'pkg' | 'g' | 'kg' | 'ml' | 'cl' | 'dl' | 'l'
export const UNITS: Unit[] = ['pcs', 'pkg', 'g', 'kg', 'ml', 'cl', 'dl', 'l']

export type Role = 'owner' | 'admin' | 'member'

export interface HouseholdSettings {
  locale: 'da' | 'en'
  allow_negative_stock: boolean
  expiry_soon_days: number
  auto_shopping_low_stock: boolean
  remove_mode_timeout_min: number
  scan_rearm_ms: number
}

export interface Me {
  /** null for a kiosk principal */
  user: { id: UUID; username: string; display_name: string; role: Role } | null
  household: { id: UUID; name: string }
  kiosk: boolean
  settings: HouseholdSettings
}

export interface Location {
  id: UUID
  name: string
  icon: string | null
  sort_order: number
  is_default: boolean
  deleted_at: ISODateTime | null
}

export interface Category {
  id: UUID
  name: string
  icon: string | null
  color: string | null
  sort_order: number
  deleted_at: ISODateTime | null
}

export interface Barcode {
  code: string
  raw: string
  symbology: string | null
}

export type ProductStatus = 'known' | 'unknown' | 'needs_review'

export interface Product {
  id: UUID
  version: number
  name: string
  brand: string | null
  category_id: UUID | null
  default_location_id: UUID | null
  image_url: string | null
  package_size: number | null
  package_unit: Unit | null
  stock_unit: Unit
  min_stock: number | null
  ingredients: string | null
  allergens: string[]
  nutrition: Record<string, unknown> | null
  description: string | null
  countries: string[]
  barcodes: Barcode[]
  aliases: string[]
  status: ProductStatus
  source: string
  source_attribution: string | null
  lookup_confidence: number | null
  locked_fields: string[]
  created_at: ISODateTime
  updated_at: ISODateTime
  deleted_at: ISODateTime | null
}

export interface StockBatch {
  id: UUID
  product_id: UUID
  location_id: UUID
  quantity: number
  expires_at: ISODate | null
  opened_at: ISODate | null
  created_at: ISODateTime
  updated_at: ISODateTime
}

export interface InventoryItem {
  product: Product
  total_quantity: number
  batches: StockBatch[]
  next_expiry: ISODate | null
  low_stock: boolean
}

export type TxnType = 'add' | 'remove' | 'adjust' | 'move' | 'undo'

export interface Transaction {
  id: UUID
  client_op_id: UUID
  product_id: UUID
  batch_id: UUID | null
  type: TxnType
  quantity_delta: number
  location_id: UUID | null
  to_location_id: UUID | null
  reason: string | null
  undoes_id: UUID | null
  undone: boolean
  user_id: UUID | null
  device_name: string | null
  occurred_at: ISODateTime
  created_at: ISODateTime
  product?: Product
}

export interface InventoryDetail extends InventoryItem {
  transactions: Transaction[]
}

export interface ShoppingItem {
  id: UUID
  version: number
  product_id: UUID | null
  name: string
  quantity: number
  unit: Unit | null
  category_id: UUID | null
  note: string | null
  checked: boolean
  checked_at: ISODateTime | null
  source: 'manual' | 'low_stock' | 'inventory'
  created_at: ISODateTime
  updated_at: ISODateTime
}

export interface Dashboard {
  totals: { products_in_stock: number; items: number }
  low_stock: InventoryItem[]
  expiring_soon: InventoryItem[]
  expired: InventoryItem[]
  recently_added: Transaction[]
  recently_consumed: Transaction[]
  unknown_count: number
  shopping_open_count: number
  by_location: { location: Location; item_count: number }[]
}

export interface BarcodeLookupResult {
  status: 'found' | 'created_placeholder' | 'not_found'
  product: Product | null
  source: string | null
}

// ---- sync ----
export type OpType = TxnType

export interface ClientOp {
  client_op_id: UUID
  type: OpType
  barcode?: string | null
  symbology?: string | null
  product_id?: UUID | null
  quantity: number
  location_id?: UUID | null
  to_location_id?: UUID | null
  expires_at?: ISODate | null
  undoes_client_op_id?: UUID | null
  reason?: string | null
  occurred_at: ISODateTime
}

export interface OpResult {
  client_op_id: UUID
  status: 'applied' | 'duplicate' | 'rejected'
  error: string | null
  error_code?: string | null
  transaction_id: UUID | null
  product: Product | null
  total_quantity: number | null
}

export interface SyncOpsResponse {
  results: OpResult[]
  server_time: ISODateTime
}

export interface SyncSnapshot {
  cursor: string
  products: Product[]
  inventory: { product_id: UUID; total_quantity: number; batches: StockBatch[] }[]
  locations: Location[]
  categories: Category[]
  settings: HouseholdSettings
}

export interface SyncChanges {
  cursor: string
  products: Product[]
  inventory: { product_id: UUID; total_quantity: number; batches: StockBatch[] }[]
  locations: Location[]
  categories: Category[]
  full_resync_required: boolean
}

// ---- AI ----
export interface AiStatus {
  enabled: boolean
  reachable: boolean
  model: string | null
}
export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}
export interface Recipe {
  title: string
  description: string
  have: string[]
  missing: string[]
  substitutions: string[]
  steps: string[]
}

// ---- additions (web app) ----
export interface StatsResponse {
  top_added: { product_id: UUID; name: string; quantity: number }[]
  top_consumed: { product_id: UUID; name: string; quantity: number }[]
  daily: { date: ISODate; added: number; removed: number }[]
}

export interface AdminUser {
  id: UUID
  username: string
  display_name: string
  role: Role
  is_active?: boolean
  created_at?: ISODateTime
}

export interface DeviceInfo {
  id: UUID
  kind: 'browser' | 'device' | 'kiosk'
  device_name: string | null
  platform: string | null
  user_id: UUID | null
  username: string | null
  created_at: ISODateTime
  last_used_at: ISODateTime
  expires_at: ISODateTime
  current: boolean
}

export interface KioskCode {
  code: string
  expires_at: ISODateTime
}

export interface ProviderInfo {
  id?: string
  name: string
  enabled: boolean
  requires_key?: boolean
  api_key?: string | null // masked, never the real key
  has_key?: boolean
}

export interface CatalogueStatus {
  counts?: Record<string, unknown>
  by_status?: Record<string, number>
  by_source?: Record<string, number>
  failed_lookups?: { barcode?: string; raw?: string; status?: string; provider?: string; created_at?: string; error?: string | null }[]
  duplicate_candidates?: { a?: Product; b?: Product; ids?: UUID[]; names?: string[]; reason?: string; similarity?: number }[]
  lookup_stats?: Record<string, number | string | null>
}

export interface AiIdentifySuggestion {
  name: string | null
  brand: string | null
  package_size: number | null
  package_unit: Unit | null
  category_guess: string | null
  confidence: number | null
}

export interface ChatReply {
  reply: string
  tool_calls: { name: string; arguments: Record<string, unknown> }[]
  model: string | null
}
