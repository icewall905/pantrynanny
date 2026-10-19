package dk.pantrynanny.app.data.remote

import dk.pantrynanny.app.data.SettingsStore
import dk.pantrynanny.app.data.TokenStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.serialization.KSerializer
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
    /** Disk cache for product images (`/api/media/*` is immutable, so it also serves them offline). */
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

    /** PATCH with If-Match. On 409 the caller finds the current Product in [ApiResult.HttpError.body]. */
    suspend fun patchProduct(id: String, version: Int, fields: JsonObject): ApiResult<ProductDto> =
        send(
            "PATCH", "api/products/$id",
            body = fields.toString(),
            headers = mapOf("If-Match" to version.toString()),
            serializer = ProductDto.serializer(),
        )

    // ---- Plumbing ---------------------------------------------------------------------------

    /** Multipart photo upload; the server re-encodes to WebP, strips EXIF and locks the image field. */
    suspend fun uploadPhoto(productId: String, jpeg: ByteArray): ApiResult<ProductDto> {
        val form = MultipartBody.Builder()
            .setType(MultipartBody.FORM)
            .addFormDataPart("file", "photo.jpg", jpeg.toRequestBody("image/jpeg".toMediaType()))
            .build()
        return send(
            "POST", "api/products/$productId/photo",
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
    ): ApiResult<T> {
        return when (val raw = execute(method, path, body, query, headers, long, baseOverride, authenticated, requestBody)) {
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
    ): ApiResult<RawResponse> = withContext(Dispatchers.IO) {
        try {
            val base = baseOverride ?: settings.current().serverUrl
            val url = buildUrl(base, path, query)
                ?: return@withContext ApiResult.NetworkError(IOException("Invalid server URL"))
            val builder = Request.Builder().url(url).header("Accept", "application/json")
            headers.forEach { (k, v) -> builder.header(k, v) }
            when (method) {
                "GET" -> builder.get()
                else -> builder.method(method, requestBody ?: (body ?: "").toRequestBody(jsonType))
            }
            val http = if (long) longClient else client
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
