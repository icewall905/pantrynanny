import type { ClientOp, InventoryItem, StockBatch, UUID } from '../api/types'

export interface PendingRecord {
  client_op_id: UUID
  seq: number
  op: ClientOp
  /** Optimistic effect on the product's displayed quantity. */
  delta: number
  /** Product id resolved locally at enqueue time (null → unknown barcode). */
  product_key: UUID | null
  /** Normalised barcode code (for products unknown locally). */
  code: string | null
  created: number
  /** Set (durably) right before the first upload attempt: the server may have applied it. */
  sent?: boolean
  /** Consecutive HTTP 500 responses for this op when sent on its own. */
  fails500?: number
}

export interface FailedRecord {
  client_op_id: UUID
  seq: number
  op: ClientOp
  error: string
  /** Machine code from OpResult.error_code (or bad_request / server_error). */
  error_code?: string | null
  at: string
}

export interface HistoryRecord {
  client_op_id: UUID
  seq: number
  at: string
  type: 'add' | 'remove'
  barcode: string
  code: string
  symbology: string | null
  product_id: UUID | null
  delta: number
  undone: boolean
}

export interface InventoryRecord {
  product_id: UUID
  server_total: number
  batches: StockBatch[]
}

export interface SyncStatus {
  online: boolean
  pending: number
  syncing: boolean
  lastSyncAt: string | null
  error: string | null
  /** Ops the server rejected; kept for the user to review. */
  failed: number
}

export type { ClientOp, InventoryItem }
