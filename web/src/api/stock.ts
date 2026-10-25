// Placement after a scan and bulk fix-up (see docs/api-contract.md).
import { post } from './client'
import type { BatchFixUpIn, BatchFixUpOut, OpResult, PlaceIn } from './types'

/** Move exactly what one applied "add" put in stock to a new expiry and/or location. */
export const placeAdded = (body: PlaceIn) => post<OpResult>('/inventory/place', { ...body }, { timeoutMs: 8000 })

/** Set location and/or expiry on many batches at once (each batch is moved whole). */
export const fixUpBatches = (body: BatchFixUpIn) => post<BatchFixUpOut>('/batches/fix-up', { ...body })
