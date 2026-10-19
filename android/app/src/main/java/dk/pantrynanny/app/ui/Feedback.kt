package dk.pantrynanny.app.ui

import android.content.Context
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import dk.pantrynanny.app.domain.ScanMode

/** Beep + vibration confirmation for a counted scan. Both are optional (settings). */
class Feedback(context: Context) {
    private val tone: ToneGenerator? = try {
        ToneGenerator(AudioManager.STREAM_NOTIFICATION, 80)
    } catch (_: RuntimeException) {
        null
    }

    private val vibrator: Vibrator? = findVibrator(context)

    fun signal(mode: ScanMode, sound: Boolean, vibrate: Boolean) {
        if (sound) {
            tone?.startTone(if (mode == ScanMode.ADD) ToneGenerator.TONE_PROP_BEEP else ToneGenerator.TONE_PROP_BEEP2, 90)
        }
        if (vibrate) {
            val ms = if (mode == ScanMode.ADD) 30L else 70L
            vibrator?.vibrate(VibrationEffect.createOneShot(ms, VibrationEffect.DEFAULT_AMPLITUDE))
        }
    }

    fun release() {
        tone?.release()
    }

    @Suppress("DEPRECATION")
    private fun findVibrator(context: Context): Vibrator? =
        if (Build.VERSION.SDK_INT >= 31) {
            context.getSystemService(VibratorManager::class.java)?.defaultVibrator
        } else {
            context.getSystemService(Context.VIBRATOR_SERVICE) as? Vibrator
        }
}
