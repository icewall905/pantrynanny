package dk.pantrynanny.app.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// Feature screens (online): the same JSON the web app uses. Unknown fields are ignored.

@Serializable
data class BatchDto(
    val id: String,
    @SerialName("location_id") val locationId: String? = null,
    val quantity: Double = 0.0,
    @SerialName("expires_at") val expiresAt: String? = null,
)

@Serializable
data class TransactionDto(
    val id: String,
    @SerialName("client_op_id") val clientOpId: String = "",
    @SerialName("product_id") val productId: String = "",
    val type: String = "",
    @SerialName("quantity_delta") val quantityDelta: Double = 0.0,
    val reason: String? = null,
    val undone: Boolean = false,
    @SerialName("device_name") val deviceName: String? = null,
    @SerialName("occurred_at") val occurredAt: String = "",
    @SerialName("created_at") val createdAt: String = "",
    val product: ProductDto? = null,
    @SerialName("user_name") val userName: String? = null,
)

@Serializable
data class InventoryItemDto(
    val product: ProductDto,
    @SerialName("total_quantity") val totalQuantity: Double = 0.0,
    val batches: List<BatchDto> = emptyList(),
    @SerialName("next_expiry") val nextExpiry: String? = null,
    @SerialName("low_stock") val lowStock: Boolean = false,
    val transactions: List<TransactionDto> = emptyList(),
)

@Serializable
data class DashboardTotalsDto(
    @SerialName("products_in_stock") val productsInStock: Int = 0,
    val items: Double = 0.0,
)

@Serializable
data class DashboardDto(
    val totals: DashboardTotalsDto = DashboardTotalsDto(),
    @SerialName("low_stock") val lowStock: List<InventoryItemDto> = emptyList(),
    @SerialName("expiring_soon") val expiringSoon: List<InventoryItemDto> = emptyList(),
    val expired: List<InventoryItemDto> = emptyList(),
    @SerialName("unknown_count") val unknownCount: Int = 0,
    @SerialName("shopping_open_count") val shoppingOpenCount: Int = 0,
)

@Serializable
data class RunOutDto(
    @SerialName("product_id") val productId: String,
    val name: String = "",
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("total_quantity") val totalQuantity: Double = 0.0,
    @SerialName("stock_unit") val stockUnit: String = "pcs",
    @SerialName("days_left") val daysLeft: Double = 0.0,
    val confidence: String = "medium",
)

@Serializable
data class ShoppingItemDto(
    val id: String,
    val version: Int = 1,
    @SerialName("product_id") val productId: String? = null,
    val name: String = "",
    val quantity: Double = 1.0,
    val unit: String? = null,
    @SerialName("category_id") val categoryId: String? = null,
    val note: String? = null,
    val store: String? = null,
    val checked: Boolean = false,
)

@Serializable
data class IngredientDto(
    val id: String,
    val raw: String = "",
    val name: String = "",
    val quantity: Double? = null,
    val unit: String? = null,
    val note: String? = null,
    val optional: Boolean = false,
    @SerialName("product_id") val productId: String? = null,
)

@Serializable
data class RecipeDto(
    val id: String,
    val version: Int = 1,
    val title: String = "",
    val description: String? = null,
    val servings: Int = 4,
    @SerialName("prep_min") val prepMin: Int? = null,
    @SerialName("cook_min") val cookMin: Int? = null,
    val instructions: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    @SerialName("source_url") val sourceUrl: String? = null,
    @SerialName("source_name") val sourceName: String? = null,
    @SerialName("image_url") val imageUrl: String? = null,
    val ingredients: List<IngredientDto> = emptyList(),
) {
    val totalMinutes: Int get() = (prepMin ?: 0) + (cookMin ?: 0)
}

@Serializable
data class MatchedProductDto(
    val id: String,
    val name: String = "",
    @SerialName("total_quantity") val totalQuantity: Double = 0.0,
    @SerialName("stock_unit") val stockUnit: String = "pcs",
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("next_expiry") val nextExpiry: String? = null,
)

@Serializable
data class IngredientAvailabilityDto(
    val ingredient: IngredientDto,
    val status: String = "missing",
    val product: MatchedProductDto? = null,
    val need: Double? = null,
    val enough: Boolean? = null,
    val expiring: Boolean = false,
)

@Serializable
data class AvailabilityDto(
    val servings: Int = 4,
    val have: Int = 0,
    val missing: Int = 0,
    val required: Int = 0,
    val coverage: Double = 0.0,
    @SerialName("uses_expiring") val usesExpiring: List<String> = emptyList(),
    val items: List<IngredientAvailabilityDto> = emptyList(),
)

@Serializable
data class RecipeSummaryDto(val recipe: RecipeDto, val availability: AvailabilityDto)

@Serializable
data class RecipeDraftDto(
    val title: String = "",
    val description: String? = null,
    val servings: Int? = null,
    @SerialName("prep_min") val prepMin: Int? = null,
    @SerialName("cook_min") val cookMin: Int? = null,
    val ingredients: List<String> = emptyList(),
    val instructions: List<String> = emptyList(),
    val tags: List<String> = emptyList(),
    @SerialName("image_url") val imageUrl: String? = null,
    @SerialName("source_url") val sourceUrl: String? = null,
    @SerialName("source_name") val sourceName: String? = null,
)

@Serializable
data class ShoppingFromDto(val added: List<String> = emptyList(), val skipped: List<String> = emptyList())

@Serializable
data class MealDto(
    val id: String,
    val day: String,
    val slot: String = "dinner",
    @SerialName("recipe_id") val recipeId: String? = null,
    @SerialName("recipe_title") val recipeTitle: String? = null,
    val title: String? = null,
    val servings: Int? = null,
    @SerialName("cooked_at") val cookedAt: String? = null,
    val missing: Int? = null,
)

@Serializable
data class ChatMessageDto(val role: String, val content: String)

@Serializable
data class ProposalDto(
    val id: String,
    val kind: String,
    val label: String = "",
    val payload: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class ChatReplyDto(
    val reply: String = "",
    val proposals: List<ProposalDto> = emptyList(),
)

@Serializable
data class AiStatusDto(val enabled: Boolean = false, val reachable: Boolean = false)
