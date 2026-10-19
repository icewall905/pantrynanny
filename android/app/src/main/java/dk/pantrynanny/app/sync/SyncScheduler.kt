package dk.pantrynanny.app.sync

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import dk.pantrynanny.app.PantryApp
import dk.pantrynanny.app.data.SyncOutcome
import java.util.concurrent.TimeUnit

class SyncWorker(context: Context, params: WorkerParameters) : CoroutineWorker(context, params) {
    override suspend fun doWork(): Result {
        val container = (applicationContext as PantryApp).container
        return when (container.syncRepository.syncNow()) {
            SyncOutcome.SUCCESS, SyncOutcome.NOT_LOGGED_IN -> Result.success()
            SyncOutcome.RETRY -> Result.retry()
            SyncOutcome.AUTH_FAILED, SyncOutcome.FAILED -> Result.failure()
        }
    }
}

class SyncScheduler(private val context: Context) {
    private val connected = Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()

    /**
     * One-time unique work, APPEND_OR_REPLACE so a request made while a run is in progress still
     * gets its own run afterwards. Each run uploads everything pending in batches (and pull is
     * throttled), so bursts of scans are cheap.
     */
    fun enqueueOneTime() {
        val request = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(connected)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(ONE_TIME, ExistingWorkPolicy.APPEND_OR_REPLACE, request)
    }

    fun schedulePeriodic() {
        val request = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(connected)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 1, TimeUnit.MINUTES)
            .build()
        WorkManager.getInstance(context)
            .enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun cancelAll() {
        val wm = WorkManager.getInstance(context)
        wm.cancelUniqueWork(ONE_TIME)
        wm.cancelUniqueWork(PERIODIC)
    }

    private companion object {
        const val ONE_TIME = "pantrynanny-sync-once"
        const val PERIODIC = "pantrynanny-sync-periodic"
    }
}
