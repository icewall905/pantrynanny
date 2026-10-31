package dk.pantrynanny.app.data

import android.util.AtomicFile
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.ApiResult
import dk.pantrynanny.app.data.remote.AppJson
import dk.pantrynanny.app.data.remote.ShoppingItemDto
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.coroutines.withContext
import kotlinx.serialization.builtins.ListSerializer
import java.io.File

/** Durable last successful list, shared by the shopping screen and background sync. */
class ShoppingRepository(private val api: ApiClient, file: File) {
    private val disk = AtomicFile(file)
    private val mutex = Mutex()
    private val serializer = ListSerializer(ShoppingItemDto.serializer())

    suspend fun cached(): List<ShoppingItemDto>? = mutex.withLock { readCache() }

    suspend fun refresh(): ApiResult<List<ShoppingItemDto>> = mutex.withLock {
        when (val result = api.get("api/shopping", serializer)) {
            is ApiResult.Ok -> {
                try {
                    withContext(Dispatchers.IO) {
                        val stream = disk.startWrite()
                        try {
                            stream.write(AppJson.encodeToString(serializer, result.value).toByteArray(Charsets.UTF_8))
                            disk.finishWrite(stream)
                        } catch (e: Exception) {
                            disk.failWrite(stream)
                            throw e
                        }
                    }
                } catch (e: java.io.IOException) {
                    return@withLock ApiResult.NetworkError(e)
                }
                result
            }
            else -> result // Never replace a good cache with an error or an empty placeholder.
        }
    }

    suspend fun clear() = mutex.withLock { withContext(Dispatchers.IO) { disk.delete() } }

    private suspend fun readCache(): List<ShoppingItemDto>? = withContext(Dispatchers.IO) {
        try {
            disk.openRead().bufferedReader(Charsets.UTF_8).use {
                AppJson.decodeFromString(serializer, it.readText())
            }
        } catch (_: java.io.IOException) {
            null
        } catch (_: IllegalArgumentException) {
            null
        }
    }
}
