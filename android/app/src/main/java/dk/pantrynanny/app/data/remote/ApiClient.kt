package dk.pantrynanny.app.data.remote

import dk.pantrynanny.app.data.SettingsStore
import dk.pantrynanny.app.data.TokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import okhttp3.Cache
import okhttp3.HttpUrl
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import java.io.File
import java.io.IOException
import java.util.concurrent.TimeUnit

sealed interface ApiResult<out T> {
    data class Ok<T>(val value: T) : ApiResult<T>
    data class HttpError(val code: Int, val detail: String?, val body: String?) : ApiResult<Nothing>
    data class NetworkError(val cause: Throwable) : ApiResult<Nothing>
}

private class RawResponse(val code: Int, val body: String)

class ApiClient(
    private val settings: SettingsStore,
    private val tokens: TokenStore,
    /** Disk cache for product images (media files are immutable, so the cache also serves them offline). */
    imageCacheDir: File? = null,
) {
    private val client: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .addInterceptor { chain ->
            val token = tokens.token()
            val request = if (token != null) {
                chain.request().newBuilder().header("Authorization", "Bearer $token").build()
            } else {
                chain.request()
            }
            chain.proceed(request)
        }
        .build()

    /** Snapshot downloads can be large: allow a longer read timeout. */
    private val longClient: OkHttpClient = client.newBuilder().readTimeout(60, TimeUnit.SECONDS).build()

    /** The assistant waits for a local AI model, which can take minutes. */
    private val slowClient: OkHttpClient = client.newBuilder().readTimeout(200, TimeUnit.SECONDS).build()

    // Separate client WITHOUT the auth interceptor: media is public, and the token must never reach other hosts.
    private val imageClient: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .apply { if (imageCacheDir != null) cache(Cache(imageCacheDir, IMAGE_CACHE_BYTES)) }
        .build()

    private val jsonType = "application/json; charset=utf-8".toMediaType()

    // ---- Endpoints -------------------------------------------------------------------------

    suspend fun login(serverUrl: String, username: String, password: String, deviceName: String): ApiResult<TokenResponse> =
        send(
            method = "POST", path = "api/auth/token",
            body = AppJson.encodeToString(TokenRequest.serializer(), TokenRequest(username, password, deviceName)),
            serializer = TokenResponse.serializer(),
            baseOverride = serverUrl,
            authenticated = false,
        )

    suspend fun logout(): ApiResult<Unit> = sendNoContent("POST", "api/auth/logout", "{}")

    suspend fun postOps(deviceId: String, ops: List<OpDto>): ApiResult<OpsResponse> =
        send(
            "POST", "api/sync/ops",
            body = AppJson.encodeToString(OpsRequest.serializer(), OpsRequest(deviceId, ops)),
            serializer = OpsResponse.serializer(),
        )

    suspend fun snapshot(): ApiResult<SnapshotDto> =
        send("GET", "api/sync/snapshot", serializer = SnapshotDto.serializer(), long = true)

    suspend fun changes(since: String): ApiResult<ChangesDto> =
        send(
            "GET", "api/sync/changes",
            query = mapOf("since" to since),
            serializer = ChangesDto.serializer(),
            long = true,
        )

    suspend fun getProduct(id: String): ApiResult<ProductDto> =
        send("GET", "api/products/$id", serializer = ProductDto.serializer())

    /** Barcode lookup incl. external providers (up to ~3 s server-side). A raw value containing '/' cannot be sent. */
    suspend fun byBarcode(raw: String, symbology: String?): ApiResult<BarcodeLookupDto> {
        if ('/' in raw) return ApiResult.HttpError(400, "unsupported barcode", null)
        val query = buildMap {
            put("lookup", "true")
            if (symbology != null) put("symbology", symbology)
        }
        return send("GET", "api/products/by-barcode/$raw", query = query, serializer = BarcodeLookupDto.serializer())
    }

    /** PATCH with If-Match. On 409 the caller finds the current Product in [ApiResult.HttpError.body]. */
    suspend fun patchProduct(id: String, version: Int, fields: JsonObject): ApiResult<ProductDto> =
        send(
            "PATCH", "api/products/$id",
            body = fields.toString(),
            headers = mapOf("If-Match" to version.toString()),
            serializer = ProductDto.serializer(),
        )

    // ---- Generic JSON calls (feature screens: shopping, recipes, meal plan, ...) ----------------

    suspend fun <T> get(path: String, serializer: KSerializer<T>, query: Map<String, String> = emptyMap()): ApiResult<T> =
        send("GET", path, query = query, serializer = serializer)

    suspend fun <T> post(path: String, body: JsonElement?, serializer: KSerializer<T>, slow: Boolean = false): ApiResult<T> =
        send("POST", path, body = body?.toString() ?: "{}", serializer = serializer, slow = slow)

    suspend fun <T> put(path: String, body: JsonElement, serializer: KSerializer<T>): ApiResult<T> =
        send("PUT", path, body = body.toString(), serializer = serializer)

    suspend fun <T> patch(path: String, body: JsonElement, serializer: KSerializer<T>, ifMatch: Int? = null): ApiResult<T> =
        send(
            "PATCH", path, body = body.toString(), serializer = serializer,
            headers = if (ifMatch != null) mapOf("If-Match" to ifMatch.toString()) else emptyMap(),
        )

    /** For endpoints whose response body the caller does not need (204, or JSON it ignores). */
    suspend fun call(method: String, path: String, body: JsonElement? = null): ApiResult<Unit> =
        sendNoContent(method, path, body?.toString() ?: if (method == "DELETE") null else "{}")

    // ---- Plumbing ---------------------------------------------------------------------------

    /** Multipart photo upload; the server re-encodes to WebP, strips EXIF and locks the image field. */
    suspend fun uploadPhoto(productId: String, jpeg: ByteArray, snapshot: Boolean = false): ApiResult<ProductDto> {
        val form = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", "photo.jpg", jpeg.toRequestBody("image/jpeg".toMediaType()))
            .build()
        return send(
            "POST", "api/products/$productId/photo",
            query = if (snapshot) mapOf("snapshot" to "true") else emptyMap(),
            requestBody = form, serializer = ProductDto.serializer(), long = true,
        )
    }

    /** Bytes of a product image (`image_url` is server-relative, e.g. `/api/media/<uuid>.webp`); null on any failure. */
    suspend fun fetchImage(imageUrl: String): ByteArray? = withContext(Dispatchers.IO) {
        try {
            val url = if (imageUrl.startsWith("http://") || imageUrl.startsWith("https://")) {
                imageUrl.toHttpUrlOrNull()
            } else {
                buildUrl(settings.current().serverUrl, imageUrl)
            } ?: return@withContext null
            imageClient.newCall(Request.Builder().url(url).build()).execute().use { r ->
                if (r.isSuccessful) r.body.bytes() else null
            }
        } catch (e: IOException) {
            null
        } catch (e: IllegalArgumentException) {
            null
        }
    }

    private suspend fun <T> send(
        method: String,
        path: String,
        body: String? = null,
        query: Map<String, String> = emptyMap(),
        headers: Map<String, String> = emptyMap(),
        serializer: KSerializer<T>,
        long: Boolean = false,
        baseOverride: String? = null,
        authenticated: Boolean = true,
        requestBody: RequestBody? = null,
        slow: Boolean = false,
    ): ApiResult<T> {
        return when (val raw = execute(method, path, body, query, headers, long, baseOverride, authenticated, requestBody, slow)) {
            is ApiResult.Ok -> try {
                ApiResult.Ok(AppJson.decodeFromString(serializer, raw.value.body))
            } catch (e: Exception) {
                ApiResult.NetworkError(IOException("Unexpected server response: ${e.message}", e))
            }
            is ApiResult.HttpError -> raw
            is ApiResult.NetworkError -> raw
        }
    }

    private suspend fun sendNoContent(method: String, path: String, body: String?): ApiResult<Unit> =
        when (val raw = execute(method, path, body, emptyMap(), emptyMap(), false, null, true)) {
            is ApiResult.Ok -> ApiResult.Ok(Unit)
            is ApiResult.HttpError -> raw
            is ApiResult.NetworkError -> raw
        }

    private suspend fun execute(
        method: String,
        path: String,
        body: String?,
        query: Map<String, String>,
        headers: Map<String, String>,
        long: Boolean,
        baseOverride: String?,
        authenticated: Boolean,
        requestBody: RequestBody? = null,
        slow: Boolean = false,
    ): ApiResult<RawResponse> = withContext(Dispatchers.IO) {
        try {
            val base = baseOverride ?: settings.current().serverUrl
            val url = buildUrl(base, path, query)
                ?: return@withContext ApiResult.NetworkError(IOException("Invalid server URL"))
            val builder = Request.Builder().url(url).header("Accept", "application/json")
            headers.forEach { (k, v) -> builder.header(k, v) }
            when {
                method == "GET" -> builder.get()
                method == "DELETE" && body == null && requestBody == null -> builder.delete()
                else -> builder.method(method, requestBody ?: (body ?: "").toRequestBody(jsonType))
            }
            val http = when {
                slow -> slowClient
                long -> longClient
                else -> client
            }
            http.newCall(builder.build()).execute().use { response ->
                val text = response.body.string()
                if (response.isSuccessful) {
                    ApiResult.Ok(RawResponse(response.code, text))
                } else {
                    ApiResult.HttpError(response.code, errorMessage(text), text)
                }
            }
        } catch (e: IOException) {
            ApiResult.NetworkError(e)
        } catch (e: IllegalArgumentException) {
            ApiResult.NetworkError(e)
        }
    }

    companion object {
        private const val IMAGE_CACHE_BYTES = 50L * 1024 * 1024

        fun buildUrl(base: String, path: String, query: Map<String, String> = emptyMap()): HttpUrl? {
            val builder = base.trim().trimEnd('/').toHttpUrlOrNull()?.newBuilder() ?: return null
            path.split('/').filter { it.isNotEmpty() }.forEach { builder.addPathSegment(it) }
            query.forEach { (k, v) -> builder.addQueryParameter(k, v) }
            return builder.build()
        }
    }
}
