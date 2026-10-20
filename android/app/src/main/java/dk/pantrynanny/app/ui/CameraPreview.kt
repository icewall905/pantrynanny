package dk.pantrynanny.app.ui

import android.util.Log
import android.util.Size
import androidx.annotation.OptIn
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.google.mlkit.vision.barcode.BarcodeScanner
import com.google.mlkit.vision.barcode.BarcodeScannerOptions
import com.google.mlkit.vision.barcode.BarcodeScanning
import com.google.mlkit.vision.barcode.common.Barcode
import com.google.mlkit.vision.common.InputImage
import dk.pantrynanny.app.domain.DecodedBarcode
import dk.pantrynanny.app.domain.FrameCandidate
import dk.pantrynanny.app.domain.FrameSelector
import java.util.concurrent.Executor
import java.util.concurrent.Executors

private const val TAG = "CameraPreview"

/**
 * Retail formats only; restricting formats makes ML Kit faster and avoids false positives. CODE_128/ITF are
 * only decoded when [others] ("Andre stregkodetyper") is on: they produce many partial misreads on EAN labels.
 */
private fun scannerOptions(others: Boolean): BarcodeScannerOptions {
    val retail = intArrayOf(Barcode.FORMAT_EAN_13, Barcode.FORMAT_EAN_8, Barcode.FORMAT_UPC_A, Barcode.FORMAT_UPC_E)
    val formats = if (others) retail + intArrayOf(Barcode.FORMAT_CODE_128, Barcode.FORMAT_ITF) else retail
    return BarcodeScannerOptions.Builder()
        .setBarcodeFormats(formats.first(), *formats.drop(1).toIntArray())
        .build()
}

fun symbologyFor(format: Int): String = when (format) {
    Barcode.FORMAT_EAN_13 -> "ean_13"
    Barcode.FORMAT_EAN_8 -> "ean_8"
    Barcode.FORMAT_UPC_A -> "upc_a"
    Barcode.FORMAT_UPC_E -> "upc_e"
    Barcode.FORMAT_CODE_128 -> "code_128"
    Barcode.FORMAT_CODE_39 -> "code_39"
    Barcode.FORMAT_ITF -> "itf"
    Barcode.FORMAT_QR_CODE -> "qr"
    Barcode.FORMAT_DATA_MATRIX -> "data_matrix"
    else -> "other"
}

private val DirectExecutor = Executor { it.run() }

private class BarcodeAnalyzer(
    private val scanner: BarcodeScanner,
    private val executor: Executor,
    private val onBarcode: (DecodedBarcode) -> Unit,
) : ImageAnalysis.Analyzer {

    /** Posts to the analysis thread but swallows RejectedExecutionException after the camera was disposed. */
    private val safeExecutor = Executor { r ->
        try {
            executor.execute(r)
        } catch (_: java.util.concurrent.RejectedExecutionException) {
        }
    }

    @OptIn(ExperimentalGetImage::class)
    override fun analyze(imageProxy: ImageProxy) {
        val media = imageProxy.image
        if (media == null) {
            imageProxy.close()
            return
        }
        try {
            val rotation = imageProxy.imageInfo.rotationDegrees
            // ML Kit reports boxes in the rotated (upright) image, so swap the sides for 90/270.
            val (w, h) = FrameSelector.uprightSize(media.width, media.height, rotation)
            val input = InputImage.fromMediaImage(media, rotation)
            scanner.process(input)
                .addOnSuccessListener(safeExecutor) { barcodes ->
                    // One barcode per frame: the most central one that does not touch the frame edge.
                    val cands = barcodes.mapNotNull { b ->
                        val value = b.rawValue
                        val box = b.boundingBox
                        if (value.isNullOrEmpty() || box == null) null
                        else FrameCandidate(Pair(value, b.format), box.left, box.top, box.right, box.bottom)
                    }
                    val (pick, box, weak) = FrameSelector.select(cands, w, h) ?: return@addOnSuccessListener
                    onBarcode(DecodedBarcode(pick.first, pick.second, box, weak))
                }
                // Direct executor: close() must run even if `executor` was shut down (RejectedExecutionException).
                .addOnCompleteListener(DirectExecutor) { imageProxy.close() }
        } catch (e: Exception) {
            Log.w(TAG, "analyze failed", e)
            imageProxy.close()
        }
    }
}

/**
 * CameraX preview + ImageAnalysis (KEEP_ONLY_LATEST, ~1280x720, dedicated background thread)
 * feeding ML Kit. [onBarcode] is invoked on the analysis thread for every decoded frame.
 */
@Composable
fun CameraPreview(
    torchOn: Boolean,
    onBarcode: (DecodedBarcode) -> Unit,
    modifier: Modifier = Modifier,
    frontCamera: Boolean = false,
    /** Also decode CODE_128/ITF (setting "Andre stregkodetyper"). */
    otherFormats: Boolean = false,
    /** Called once the camera provider is known: true when the device has both a front and a rear camera. */
    onCanSwitch: (Boolean) -> Unit = {},
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    val previewView = remember {
        PreviewView(context).apply { scaleType = PreviewView.ScaleType.FILL_CENTER }
    }
    var camera by remember { mutableStateOf<Camera?>(null) }
    val currentOnBarcode by rememberUpdatedState(onBarcode)
    val currentOnCanSwitch by rememberUpdatedState(onCanSwitch)

    // Keyed on the lens too: switching cameras unbinds and rebinds the use cases.
    DisposableEffect(lifecycleOwner, frontCamera, otherFormats) {
        val executor = Executors.newSingleThreadExecutor()
        val scanner = BarcodeScanning.getClient(scannerOptions(otherFormats))
        val providerFuture = ProcessCameraProvider.getInstance(context)
        var provider: ProcessCameraProvider? = null
        var disposed = false

        providerFuture.addListener({
            try {
                val p = providerFuture.get()
                if (disposed) return@addListener
                provider = p
                val preview = Preview.Builder().build()
                preview.setSurfaceProvider(previewView.surfaceProvider)
                val resolution = ResolutionSelector.Builder()
                    .setResolutionStrategy(
                        ResolutionStrategy(Size(1280, 720), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)
                    )
                    .build()
                val analysis = ImageAnalysis.Builder()
                    .setResolutionSelector(resolution)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .build()
                analysis.setAnalyzer(executor, BarcodeAnalyzer(scanner, executor) { currentOnBarcode(it) })
                val hasFront = p.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA)
                val hasBack = p.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA)
                currentOnCanSwitch(hasFront && hasBack)
                // PreviewView mirrors the front camera itself; ML Kit reads the unmirrored frames.
                val selector = if ((frontCamera && hasFront) || !hasBack) {
                    CameraSelector.DEFAULT_FRONT_CAMERA
                } else {
                    CameraSelector.DEFAULT_BACK_CAMERA
                }
                p.unbindAll()
                camera = p.bindToLifecycle(lifecycleOwner, selector, preview, analysis)
            } catch (e: Exception) {
                Log.e(TAG, "Camera start failed", e)
            }
        }, ContextCompat.getMainExecutor(context))

        onDispose {
            disposed = true
            camera = null
            try {
                provider?.unbindAll()
            } catch (e: Exception) {
                Log.w(TAG, "unbind failed", e)
            }
            executor.shutdown()
            scanner.close()
        }
    }

    LaunchedEffect(camera, torchOn) {
        camera?.cameraControl?.enableTorch(torchOn)
    }

    AndroidView(factory = { previewView }, modifier = modifier)
}
