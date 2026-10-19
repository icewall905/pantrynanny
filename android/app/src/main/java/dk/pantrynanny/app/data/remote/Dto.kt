package dk.pantrynanny.app.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonPrimitive

/** Shared JSON configuration: tolerant on input, compact on output. */
val AppJson: Json = Json {
    ignoreUnknownKeys = true
    isLenient = true
    coerceInputValues = true
    encodeDefaults = true
    explicitNulls = false
}

@Serializable
data class BarcodeDto(
    val code: String,
    val raw: String = "",
    val symbology: String? = null,
)

@Serializable
data class ProductDto(
    val id: String,
    val version: Int = 1,
    val name: String = "",
    val brand: String? = null,
    @SerialName("category_id") val categoryId: String? = null,
    @SerialName("default_location_id") val defaultLocationId: String? = null,
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("package_size") val packageSize: Double? = null,
    @SerialName("package_unit") val packageUnit: String? = null,
    @SerialName("stock_unit") val stockUnit: String = "pcs",
    @SerialName("min_stock") val minStock: Double? = null,
    val aliases: List<String> = emptyList(),
    val barcodes: List<BarcodeDto> = emptyList(),
    val status: String = "known",
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class StockBatchDto(
    val id: String,
    @SerialName("product_id") val productId: String? = null,
    @SerialName("location_id") val locationId: String? = null,
    val quantity: Double = 0.0,
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("opened_at") val openedAt: String? = null,
)

@Serializable
data class InventoryEntryDto(
    @SerialName("product_id") val productId: String,
    @SerialName("total_quantity") val totalQuantity: Double = 0.0,
    val batches: List<StockBatchDto> = emptyList(),
)

@Serializable
data class LocationDto(
    val id: String,
    val name: String = "",
    val icon: String? = null,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("is_default") val isDefault: Boolean = false,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class CategoryDto(
    val id: String,
    val name: String = "",
    val icon: String? = null,
    val color: String? = null,
    @SerialName("sort_order") val sortOrder: Int = 0,
    @SerialName("deleted_at") val deletedAt: String? = null,
)

@Serializable
data class HouseholdSettingsDto(
    val locale: String? = null,
    @SerialName("remove_mode_timeout_min") val removeModeTimeoutMin: Int = 10,
    @SerialName("scan_rearm_ms") val scanRearmMs: Int = 600,
)

@Serializable
data class SnapshotDto(
    val cursor: String = "",
    val products: List<ProductDto> = emptyList(),
    val inventory: List<InventoryEntryDto> = emptyList(),
    val locations: List<LocationDto> = emptyList(),
    val categories: List<CategoryDto> = emptyList(),
    val settings: HouseholdSettingsDto? = null,
)

@Serializable
data class ChangesDto(
    val cursor: String = "",
    val products: List<ProductDto> = emptyList(),
    val inventory: List<InventoryEntryDto> = emptyList(),
    val locations: List<LocationDto> = emptyList(),
    val categories: List<CategoryDto> = emptyList(),
    @SerialName("full_resync_required") val fullResyncRequired: Boolean = false,
)

@Serializable
data class OpDto(
    @SerialName("client_op_id") val clientOpId: String,
    val type: String,
    val barcode: String? = null,
    val symbology: String? = null,
    @SerialName("product_id") val productId: String? = null,
    val quantity: Double = 1.0,
    @SerialName("location_id") val locationId: String? = null,
    @SerialName("to_location_id") val toLocationId: String? = null,
    @SerialName("expires_at") val expiresAt: String? = null,
    @SerialName("undoes_client_op_id") val undoesClientOpId: String? = null,
    @SerialName("occurred_at") val occurredAt: String,
)

@Serializable
data class OpsRequest(
    @SerialName("device_id") val deviceId: String,
    val ops: List<OpDto>,
)

@Serializable
data class OpResultDto(
    @SerialName("client_op_id") val clientOpId: String,
    val status: String,
    val error: String? = null,
    @SerialName("error_code") val errorCode: String? = null,
    @SerialName("transaction_id") val transactionId: String? = null,
    val product: ProductDto? = null,
    @SerialName("total_quantity") val totalQuantity: Double? = null,
)

@Serializable
data class OpsResponse(
    val results: List<OpResultDto> = emptyList(),
    @SerialName("server_time") val serverTime: String? = null,
)

@Serializable
data class TokenRequest(
    val username: String,
    val password: String,
    @SerialName("device_name") val deviceName: String,
    val platform: String = "android",
)

@Serializable
data class UserDto(
    val id: String = "",
    val username: String = "",
    @SerialName("display_name") val displayName: String? = null,
    val role: String = "member",
)

@Serializable
data class HouseholdDto(val id: String = "", val name: String = "")

@Serializable
data class MeDto(
    val user: UserDto? = null, // null for a kiosk principal
    val household: HouseholdDto? = null,
    val kiosk: Boolean = false,
    val settings: HouseholdSettingsDto? = null,
)

@Serializable
data class TokenResponse(val token: String, val me: MeDto = MeDto())

@Serializable
data class ErrorBody(val detail: JsonElement? = null, val code: String? = null)

/** Human readable message from an error body ("detail" may be a string or a validation list). */
fun errorMessage(body: String?): String? {
    if (body.isNullOrBlank()) return null
    return try {
        val e = AppJson.decodeFromString(ErrorBody.serializer(), body)
        val d = e.detail
        when {
            d is JsonPrimitive -> d.content
            d != null -> d.toString()
            else -> e.code
        }
    } catch (_: Exception) {
        null
    }
}
