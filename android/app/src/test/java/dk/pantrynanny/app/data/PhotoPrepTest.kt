package dk.pantrynanny.app.data

import android.media.ExifInterface
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class PhotoPrepTest {
    @Test
    fun smallImagesAreNotSampled() {
        assertEquals(1, PhotoPrep.sampleSizeFor(1600, 1200))
        assertEquals(1, PhotoPrep.sampleSizeFor(800, 600))
        assertEquals(1, PhotoPrep.sampleSizeFor(3199, 2000))
    }

    @Test
    fun phonePhotosAreSampledButStayAboveTheTargetEdge() {
        // 12 MP, 50 MP and 200 MP sensors: the server refuses > 24 MP, so these must shrink on the phone.
        for ((w, h) in listOf(4000 to 3000, 8160 to 6120, 16320 to 12240)) {
            val edge = PhotoPrep.sampledEdge(w, h)
            assertTrue("$w x $h -> $edge", edge in PhotoPrep.MAX_EDGE until PhotoPrep.MAX_EDGE * 2)
        }
        assertEquals(2, PhotoPrep.sampleSizeFor(4000, 3000))
        assertEquals(8, PhotoPrep.sampleSizeFor(16320, 12240))
    }

    @Test
    fun portraitUsesTheLongerEdge() {
        assertEquals(PhotoPrep.sampleSizeFor(4000, 3000), PhotoPrep.sampleSizeFor(3000, 4000))
    }

    @Test
    fun exifRotation() {
        assertEquals(0, PhotoPrep.rotationDegrees(ExifInterface.ORIENTATION_NORMAL))
        assertEquals(0, PhotoPrep.rotationDegrees(ExifInterface.ORIENTATION_UNDEFINED))
        assertEquals(90, PhotoPrep.rotationDegrees(ExifInterface.ORIENTATION_ROTATE_90))
        assertEquals(180, PhotoPrep.rotationDegrees(ExifInterface.ORIENTATION_ROTATE_180))
        assertEquals(270, PhotoPrep.rotationDegrees(ExifInterface.ORIENTATION_ROTATE_270))
    }
}
