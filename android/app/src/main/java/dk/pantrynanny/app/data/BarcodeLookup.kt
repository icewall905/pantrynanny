package dk.pantrynanny.app.data

import dk.pantrynanny.app.data.local.AppDatabase
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.BarcodeLookupDto
import dk.pantrynanny.app.domain.BarcodeNormalizer
import dk.pantrynanny.app.domain.CardLookup
import kotlinx.coroutines.delay

enum class LookupOutcome {
    /** A real product was found and cached. */
    FOUND,

    /** not_found, or only a server placeholder exists: genuinely unknown (for now). */
    UNKNOWN,

    /** No answer (offline, server down, 4xx): stay neutral and keep listening to the local store. */
    FAILED,
}

/** Retry network errors and 5xx at [delaysMs]; 4xx are answers and are not retried. */
suspend fun <T> retrying(delaysMs: LongArray, call: suspend () -> ApiResult<T>): ApiResult<T> {
    var i = 0
    while (true) {
        val r = call()
        val retryable = r is ApiResult.NetworkError || (r is ApiResult.HttpError && r.code >= 500)
        if (!retryable || i >= delaysMs.size) return r
        delay(delaysMs[i++])
    }
}

/** Server-side lookup of a barcode that is not in the local cache; result is cached and linked to scan history. */
class BarcodeLookup(
    private val api: ApiClient,
    private val cache: CacheWriter,
    private val db: AppDatabase,
    private val retryDelaysMs: LongArray = CardLookup.RETRY_DELAYS_MS,
) {
    suspend fun lookup(raw: String, symbology: String?): LookupOutcome {
        val value = BarcodeNormalizer.strip(raw)
        val r = retrying(retryDelaysMs) { api.byBarcode(value, symbology) }
        val dto: BarcodeLookupDto = (r as? ApiResult.Ok)?.value ?: return LookupOutcome.FAILED
        val product = dto.product ?: return LookupOutcome.UNKNOWN
        cache.applyProduct(product)
        db.historyDao().attachProductByBarcode(raw, product.id, product.name)
        return if (product.status == "unknown" || dto.status == "created_placeholder") LookupOutcome.UNKNOWN
        else LookupOutcome.FOUND
    }
}
