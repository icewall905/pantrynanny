package dk.pantrynanny.app.data

import dk.pantrynanny.app.data.local.ProductEntity
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.AppJson
import dk.pantrynanny.app.data.remote.ProductDto
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject

sealed interface EditResult {
    data object Saved : EditResult
    data object NothingChanged : EditResult
    /** Someone else changed the product (HTTP 409); the cache now holds the server copy. */
    data object Conflict : EditResult
    data object Offline : EditResult
    data class Failed(val message: String) : EditResult
}

/** Online product-metadata edits via PATCH with If-Match (optimistic concurrency). */
class InventoryRepository(
    private val api: ApiClient,
    private val cache: CacheWriter,
) {
    suspend fun editProduct(
        current: ProductEntity,
        name: String,
        brand: String?,
        categoryId: String?,
        minStock: Double?,
        defaultLocationId: String?,
    ): EditResult {
        val fields = buildJsonObject {
            if (name != current.name) put("name", JsonPrimitive(name))
            if (brand != current.brand) put("brand", brand?.let { JsonPrimitive(it) } ?: JsonNull)
            if (categoryId != current.categoryId) put("category_id", categoryId?.let { JsonPrimitive(it) } ?: JsonNull)
            if (minStock != current.minStock) put("min_stock", minStock?.let { JsonPrimitive(it) } ?: JsonNull)
            if (defaultLocationId != current.defaultLocationId) {
                put("default_location_id", defaultLocationId?.let { JsonPrimitive(it) } ?: JsonNull)
            }
        }
        if (fields.isEmpty()) return EditResult.NothingChanged
        return when (val r = api.patchProduct(current.id, current.version, fields)) {
            is ApiResult.Ok -> {
                cache.applyProduct(r.value)
                EditResult.Saved
            }
            is ApiResult.NetworkError -> EditResult.Offline
            is ApiResult.HttpError -> {
                if (r.code == 409) {
                    refreshAfterConflict(current.id, r.body)
                    EditResult.Conflict
                } else {
                    EditResult.Failed(r.detail ?: "HTTP ${r.code}")
                }
            }
        }
    }

    private suspend fun refreshAfterConflict(id: String, body: String?) {
        val parsed = try {
            body?.let { AppJson.decodeFromString(ProductDto.serializer(), it) }?.takeIf { it.id == id }
        } catch (_: Exception) {
            null
        }
        if (parsed != null) {
            cache.applyProduct(parsed)
        } else {
            (api.getProduct(id) as? ApiResult.Ok)?.let { cache.applyProduct(it.value) }
        }
    }
}
