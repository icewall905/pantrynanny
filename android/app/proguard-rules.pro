# kotlinx.serialization
-keepattributes *Annotation*, InnerClasses
-dontnote kotlinx.serialization.AnnotationsKt
-keepclassmembers class kotlinx.serialization.json.** { *** Companion; }
-keepclasseswithmembers class kotlinx.serialization.json.** { kotlinx.serialization.KSerializer serializer(...); }
-keep,includedescriptorclasses class dk.pantrynanny.app.**$$serializer { *; }
-keepclassmembers class dk.pantrynanny.app.** { *** Companion; }
-keepclasseswithmembers class dk.pantrynanny.app.** { kotlinx.serialization.KSerializer serializer(...); }
# OkHttp / Okio optional platform classes
-dontwarn okhttp3.internal.platform.**
-dontwarn org.conscrypt.**
-dontwarn org.bouncycastle.**
-dontwarn org.openjsse.**
