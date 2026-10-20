package dk.pantrynanny.app.ui

import android.graphics.Bitmap
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
import java.util.concurrent.Executor
import java.util.concurrent.Executors

private const val TAG = "CameraPreview"

/** Retail formats only; restricting formats makes ML Kit faster and avoids false positives. */
private fun scannerOptions(): BarcodeScannerOptions =
    BarcodeScannerOptions.Builder()
        .setBarcodeFormats(
            Barcode.FORMAT_EAN_13,
            Barcode.FORMAT_EAN_8,
            Barcode.FORMAT_UPC_A,
            Barcode.FORMAT_UPC_E,
            Barcode.FORMAT_CODE_128,
            Barcode.FORMAT_ITF,
        )
        .build()

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
    private val onBarcode: (String, Int) -> Unit,
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
            val input = InputImage.fromMediaImage(media, imageProxy.imageInfo.rotationDegrees)
            scanner.process(input)
                .addOnSuccessListener(safeExecutor) { barcodes ->
                    for (b in barcodes) {
                        val value = b.rawValue
                        if (!value.isNullOrEmpty()) onBarcode(value, b.format)
                    }
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
    onBarcode: (String, Int) -> Unit,
    modifier: Modifier = Modifier,
    frontCamera: Boolean = false,
    /** Called once the camera provider is known: true when the device has both a front and a rear camera. */
    onCanSwitch: (Boolean) -> Unit = {},
    /** Receives a function returning the current preview frame (main thread; null before the first frame). */
    onFrameGrabber: ((() -> Bitmap?) -> Unit)? = null,
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
    DisposableEffect(lifecycleOwner, frontCamera) {
        val executor = Executors.newSingleThreadExecutor()
        val scanner = BarcodeScanning.getClient(scannerOptions())
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
                analysis.setAnalyzer(executor, BarcodeAnalyzer(scanner, executor) { v, f -> currentOnBarcode(v, f) })
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

    LaunchedEffect(previewView) { onFrameGrabber?.invoke { previewView.bitmap } }

    AndroidView(factory = { previewView }, modifier = modifier)
}
