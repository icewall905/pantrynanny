package dk.pantrynanny.app.data

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import android.util.Log
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Stores the bearer token encrypted with an AES-256-GCM key that lives in the Android Keystore
 * (androidx.security:security-crypto is deprecated, so this is done directly).
 */
class TokenStore(context: Context) {
    private val prefs = context.getSharedPreferences("secure_token", Context.MODE_PRIVATE)

    @Volatile
    private var cached: String? = load()

    private val _loggedIn = MutableStateFlow(cached != null)
    val loggedIn: StateFlow<Boolean> = _loggedIn

    fun token(): String? = cached

    fun save(token: String) {
        try {
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val ct = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
            val packed = Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" + Base64.encodeToString(ct, Base64.NO_WRAP)
            prefs.edit().putString(PREF_KEY, packed).apply()
        } catch (e: Exception) {
            // If the keystore is unusable keep the token in memory only (user must log in again next launch).
            Log.e(TAG, "Could not persist token securely", e)
            prefs.edit().remove(PREF_KEY).apply()
        }
        cached = token
        _loggedIn.value = true
    }

    fun clear() {
        prefs.edit().remove(PREF_KEY).apply()
        cached = null
        _loggedIn.value = false
    }

    private fun load(): String? {
        val packed = prefs.getString(PREF_KEY, null) ?: return null
        return try {
            val parts = packed.split(":")
            val iv = Base64.decode(parts[0], Base64.NO_WRAP)
            val ct = Base64.decode(parts[1], Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, iv))
            String(cipher.doFinal(ct), Charsets.UTF_8)
        } catch (e: Exception) {
            Log.e(TAG, "Could not decrypt stored token; clearing", e)
            prefs.edit().remove(PREF_KEY).apply()
            null
        }
    }

    private fun key(): SecretKey {
        val ks = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (ks.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build()
        )
        return generator.generateKey()
    }

    private companion object {
        const val TAG = "TokenStore"
        const val ALIAS = "pantrynanny_token_key"
        const val PREF_KEY = "token"
        const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
