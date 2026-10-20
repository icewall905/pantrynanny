package dk.pantrynanny.app.data

import dk.pantrynanny.app.data.remote.ApiResult
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.IOException

class RetryingTest {
    private val delays = longArrayOf(1, 1)

    @Test
    fun retriesNetworkAndServerErrorsThenSucceeds() = runBlocking {
        var n = 0
        val r = retrying(delays) {
            when (++n) {
                1 -> ApiResult.NetworkError(IOException("x"))
                2 -> ApiResult.HttpError(503, null, null)
                else -> ApiResult.Ok("ok")
            }
        }
        assertEquals(3, n)
        assertTrue(r is ApiResult.Ok)
    }

    @Test
    fun doesNotRetryClientErrors() = runBlocking {
        var n = 0
        val r = retrying(delays) { n++; ApiResult.HttpError(401, null, null) }
        assertEquals(1, n)
        assertTrue(r is ApiResult.HttpError)
    }

    @Test
    fun givesUpAfterAllDelays() = runBlocking {
        var n = 0
        retrying(delays) { n++; ApiResult.NetworkError(IOException("x")) }
        assertEquals(3, n)
    }
}
