package dk.pantrynanny.app.data

import dk.pantrynanny.app.data.local.PendingOpEntity
import dk.pantrynanny.app.data.remote.ApiClient
import dk.pantrynanny.app.data.remote.AppJson
import dk.pantrynanny.app.data.remote.ChangesDto
import dk.pantrynanny.app.data.remote.OpsRequest
import dk.pantrynanny.app.data.remote.OpsResponse
import dk.pantrynanny.app.data.remote.SnapshotDto
import dk.pantrynanny.app.data.remote.TokenRequest
import dk.pantrynanny.app.data.remote.TokenResponse
import dk.pantrynanny.app.data.remote.errorMessage
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Payloads shaped exactly like docs/api-contract.md. */
class ContractJsonTest {

    private val productJson = """
        {"id":"11111111-1111-4111-8111-111111111111","version":3,"name":"Letmælk","brand":"Arla",
         "category_id":null,"default_location_id":"22222222-2222-4222-8222-222222222222",
         "image_url":"/api/media/p/1.webp","package_size":1,"package_unit":"l","stock_unit":"pcs",
         "min_stock":2,"ingredients":null,"allergens":["milk"],"nutrition":{"kcal":42},"description":null,
         "countries":["dk"],"barcodes":[{"code":"05701234567899","raw":"5701234567899","symbology":"ean_13"}],
         "aliases":["mælk"],"status":"known","source":"openfoodfacts","source_attribution":null,
         "lookup_confidence":0.9,"locked_fields":["name"],"created_at":"2026-10-19T10:00:00Z",
         "updated_at":"2026-10-19T10:00:00Z","deleted_at":null,"some_future_field":123}
    """.trimIndent()

    @Test
    fun opsRequestMatchesContractFieldNames() {
        val op = PendingOpEntity(
            clientOpId = "c0ffee00-0000-4000-8000-000000000001",
            type = "add",
            barcode = "5701234567899",
            symbology = "ean_13",
            productId = null,
            quantity = 1.0,
            locationId = null,
            toLocationId = null,
            expiresAt = null,
            undoesClientOpId = null,
            occurredAt = "2026-10-19T12:00:00Z",
            localDelta = 1.0,
        ).toDto()
        val text = AppJson.encodeToString(OpsRequest.serializer(), OpsRequest("dev-1", listOf(op)))
        val root = Json.parseToJsonElement(text).jsonObject
        assertEquals("dev-1", root["device_id"]!!.jsonPrimitive.content)
        val o = root["ops"]!!.let { (it as kotlinx.serialization.json.JsonArray)[0].jsonObject }
        assertEquals("c0ffee00-0000-4000-8000-000000000001", o["client_op_id"]!!.jsonPrimitive.content)
        assertEquals("add", o["type"]!!.jsonPrimitive.content)
        assertEquals("5701234567899", o["barcode"]!!.jsonPrimitive.content)
        assertEquals("ean_13", o["symbology"]!!.jsonPrimitive.content)
        assertEquals("2026-10-19T12:00:00Z", o["occurred_at"]!!.jsonPrimitive.content)
        // null optionals are omitted rather than sent as null
        assertFalse(o.containsKey("product_id"))
        assertFalse(o.containsKey("undoes_client_op_id"))
        assertFalse(o.containsKey("localDelta"))
    }

    @Test
    fun undoOpCarriesReference() {
        val op = PendingOpEntity(
            clientOpId = "u1", type = "undo", barcode = null, symbology = null, productId = "p1",
            quantity = 1.0, locationId = null, toLocationId = null, expiresAt = null,
            undoesClientOpId = "orig", occurredAt = "2026-10-19T12:00:05Z", localDelta = -1.0,
        ).toDto()
        val o = AppJson.encodeToJsonElementForTest(op)
        assertEquals("orig", o["undoes_client_op_id"]!!.jsonPrimitive.content)
        assertEquals("undo", o["type"]!!.jsonPrimitive.content)
    }

    @Test
    fun opsResponseParses() {
        val text = """
            {"results":[
              {"client_op_id":"a","status":"applied","error":null,"transaction_id":"t1","product":$productJson,"total_quantity":3},
              {"client_op_id":"b","status":"duplicate","error":null,"transaction_id":"t2","product":$productJson,"total_quantity":3.5},
              {"client_op_id":"c","status":"applied","error":"clamped","transaction_id":"t3","product":$productJson,"total_quantity":0},
              {"client_op_id":"d","status":"rejected","error":"bad op","transaction_id":null,"product":null,"total_quantity":null}
            ],"server_time":"2026-10-19T12:00:01Z"}
        """.trimIndent()
        val r = AppJson.decodeFromString(OpsResponse.serializer(), text)
        assertEquals(4, r.results.size)
        assertEquals("applied", r.results[0].status)
        assertEquals(3.0, r.results[0].totalQuantity!!, 0.0)
        assertEquals(3.5, r.results[1].totalQuantity!!, 0.0)
        assertEquals("clamped", r.results[2].error)
        assertEquals("rejected", r.results[3].status)
        assertNull(r.results[3].product)
        val p = r.results[0].product!!
        assertEquals(3, p.version)
        assertEquals("Letmælk", p.name)
        assertEquals("known", p.status)
        assertEquals("05701234567899", p.barcodes[0].code)
        assertEquals(2.0, p.minStock!!, 0.0)
        assertEquals(1.0, p.packageSize!!, 0.0)
        assertEquals(listOf("mælk"), p.aliases)
    }

    @Test
    fun productToEntityBuildsSearchText() {
        val p = AppJson.decodeFromString(dk.pantrynanny.app.data.remote.ProductDto.serializer(), productJson)
        val e = p.toEntity(2.0)
        assertEquals(2.0, e.totalQuantity, 0.0)
        assertTrue(e.searchText.contains("letmælk"))
        assertTrue(e.searchText.contains("arla"))
        assertTrue(e.searchText.contains("mælk"))
        val codes = p.barcodeEntities()
        assertEquals("05701234567899", codes[0].code)
        assertEquals("5701234567899", codes[0].raw)
    }

    @Test
    fun snapshotParses() {
        val text = """
            {"cursor":"12345","products":[$productJson],
             "inventory":[{"product_id":"11111111-1111-4111-8111-111111111111","total_quantity":3,
                "batches":[{"id":"b1","product_id":"11111111-1111-4111-8111-111111111111","location_id":"l1","quantity":3,
                           "expires_at":"2026-11-01","opened_at":null,"created_at":"x","updated_at":"y"}]}],
             "locations":[{"id":"l1","name":"Køleskab","icon":"fridge","sort_order":1,"is_default":true,"deleted_at":null}],
             "categories":[{"id":"c1","name":"Mejeri","icon":null,"color":"#fff","sort_order":0,"deleted_at":null}],
             "settings":{"locale":"da","allow_negative_stock":false,"expiry_soon_days":3,
                         "auto_shopping_low_stock":true,"remove_mode_timeout_min":15,"scan_rearm_ms":800}}
        """.trimIndent()
        val s = AppJson.decodeFromString(SnapshotDto.serializer(), text)
        assertEquals("12345", s.cursor)
        assertEquals(1, s.products.size)
        assertEquals(3.0, s.inventory[0].totalQuantity, 0.0)
        assertEquals("2026-11-01", s.inventory[0].batches[0].expiresAt)
        assertEquals("Køleskab", s.locations[0].name)
        assertTrue(s.locations[0].isDefault)
        assertEquals(15, s.settings!!.removeModeTimeoutMin)
        assertEquals(800, s.settings!!.scanRearmMs)
    }

    @Test
    fun cursorMayBeANumber() {
        val c = AppJson.decodeFromString(ChangesDto.serializer(), """{"cursor":987,"products":[],"inventory":[],"locations":[],"categories":[],"full_resync_required":false}""")
        assertEquals("987", c.cursor)
    }

    @Test
    fun changesFullResyncFlag() {
        val c = AppJson.decodeFromString(ChangesDto.serializer(), """{"cursor":"","full_resync_required":true}""")
        assertTrue(c.fullResyncRequired)
        assertTrue(c.products.isEmpty())
    }

    @Test
    fun deletedProductInChanges() {
        val c = AppJson.decodeFromString(
            ChangesDto.serializer(),
            """{"cursor":"7","products":[{"id":"p","version":2,"name":"X","deleted_at":"2026-10-19T00:00:00Z"}],"inventory":[],"locations":[],"categories":[],"full_resync_required":false}""",
        )
        assertNotNull(c.products[0].deletedAt)
    }

    @Test
    fun tokenRequestAndResponse() {
        val req = AppJson.encodeToString(TokenRequest.serializer(), TokenRequest("anna", "pw", "Pixel 8"))
        val o = Json.parseToJsonElement(req).jsonObject
        assertEquals("android", o["platform"]!!.jsonPrimitive.content)
        assertEquals("Pixel 8", o["device_name"]!!.jsonPrimitive.content)

        val resp = AppJson.decodeFromString(
            TokenResponse.serializer(),
            """{"token":"abc","me":{"user":{"id":"u1","username":"anna","display_name":"Anna","role":"member"},
               "household":{"id":"h1","name":"Hjem"},"kiosk":false,
               "settings":{"locale":"da","remove_mode_timeout_min":10,"scan_rearm_ms":600}}}""",
        )
        assertEquals("abc", resp.token)
        assertEquals("Anna", resp.me.user!!.displayName)
        assertEquals(600, resp.me.settings!!.scanRearmMs)
    }

    @Test
    fun kioskMeHasNullUser() {
        val me = AppJson.decodeFromString(
            dk.pantrynanny.app.data.remote.MeDto.serializer(),
            """{"user":null,"household":{"id":"h1","name":"Hjem"},"kiosk":true,"settings":null}""",
        )
        assertNull(me.user)
        assertTrue(me.kiosk)
    }

    @Test
    fun opResultErrorCode() {
        val r = AppJson.decodeFromString(
            OpsResponse.serializer(),
            """{"results":[{"client_op_id":"a","status":"rejected","error":"nope","error_code":"product_not_found"}]}""",
        )
        assertEquals("product_not_found", r.results[0].errorCode)
    }

    @Test
    fun errorMessages() {
        assertEquals("Not found", errorMessage("""{"detail":"Not found","code":"not_found"}"""))
        assertEquals("version_conflict", errorMessage("""{"code":"version_conflict"}"""))
        assertNotNull(errorMessage("""{"detail":[{"loc":["body","name"],"msg":"field required"}]}"""))
        assertNull(errorMessage("not json"))
        assertNull(errorMessage(null))
    }

    @Test
    fun urlBuilding() {
        assertEquals("https://pantry.example.com/api/sync/snapshot", ApiClient.buildUrl("https://pantry.example.com/", "api/sync/snapshot").toString())
        assertEquals(
            "http://192.168.1.5:8000/api/sync/changes?since=a%20b",
            ApiClient.buildUrl("http://192.168.1.5:8000", "api/sync/changes", mapOf("since" to "a b")).toString(),
        )
        assertEquals("https://h.example/pn/api/auth/token", ApiClient.buildUrl("https://h.example/pn", "api/auth/token").toString())
        assertNull(ApiClient.buildUrl("not a url", "x"))
    }

    // Helper: encode a value and return it as a JsonObject.
    private fun Json.encodeToJsonElementForTest(op: dk.pantrynanny.app.data.remote.OpDto): JsonObject =
        encodeToJsonElement(dk.pantrynanny.app.data.remote.OpDto.serializer(), op).jsonObject
}
