# PantryNanny – original product brief

This is the brief PantryNanny was built from (site-specific infrastructure details replaced with placeholders).

```text
You are my autonomous senior full-stack developer, mobile developer, UI/UX designer, DevOps engineer, and software architect.

Your task is to DESIGN, BUILD, TEST, DEPLOY, and DOCUMENT a complete, production-quality, self-hosted kitchen inventory management system called PantryNanny.

This is a real project, not a prototype or mockup. Implement the actual software, make reasonable technical decisions independently, and get as much as possible fully working and deployed.

Prioritize ease of use, reliability, speed, maintainability, and excellent user experience over unnecessary complexity.

============================================================
1. PROJECT OVERVIEW
============================================================

Project name: PantryNanny

GitHub repository:
the project GitHub repository

PantryNanny is a household kitchen inventory management system designed primarily for Danish households.

Its purpose is to make tracking food, groceries, household supplies, expiration dates, and shopping needs almost effortless.

The core workflow:

1. Someone buys groceries.
2. They open PantryNanny on their Android phone or our wall-mounted iPad.
3. They select "Add" mode.
4. They scan products as they put groceries away.
5. PantryNanny recognizes products automatically and updates inventory.
6. When products are consumed, they can be scanned in "Remove" mode.
7. Everyone in the household can see the current inventory and shopping list.

The absolute most important design principle:

USING PANTRYNANNY MUST BE FASTER AND EASIER THAN MANUALLY KEEPING TRACK OF GROCERIES.

If an interaction makes scanning ten groceries tedious, redesign it.

The system consists of:

A. Self-hosted backend with PostgreSQL
B. Modern responsive web interface
C. Installable PWA optimized for our wall-mounted iPad
D. Native Android application
E. Danish barcode/product identification system
F. Offline-first local caching and synchronization
G. Optional local AI assistant
H. Deployment, administration, and backup infrastructure

All components must share the same backend, inventory, and product catalogue.

============================================================
2. INFRASTRUCTURE AND DEPLOYMENT
============================================================

GitHub:
the project GitHub repository

Proxmox VE host:
<proxmox-host>

Deployment:
Create a new LXC container on the Proxmox host.

Container hostname:
pantrynanny

The container will receive WireGuard IP:
<container-wireguard-ip>

IMPORTANT:
I will configure the WireGuard connection myself after you have created the container.

Do not invent WireGuard credentials, keys, tunnel endpoints, or network configuration.

Create the container, install everything needed, and make it ready for my WireGuard configuration.

Clearly tell me when the container is ready for WireGuard setup and provide the information needed to configure it.

You may continue installing and configuring the application through Proxmox's pct exec functionality before WireGuard is available.

The service should listen on:
0.0.0.0:8734

The reverse proxy is managed separately by me.

Reverse proxy:
Traefik at <reverse-proxy-ip>

Public URL:
https://pantry.example.com

Traefik upstream:
http://<container-wireguard-ip>:8734

I will configure the Traefik routing myself.

Your responsibilities include making sure the application supports reverse proxy headers, HTTPS termination, secure authentication cookies, WebSockets if needed, and correct external URLs.

Do not modify my Traefik installation or existing reverse proxy configuration.

Recommended infrastructure:
- Debian 13 or another appropriate stable Linux distribution
- PostgreSQL
- Python FastAPI or equivalent backend
- React + TypeScript frontend
- Nginx or equivalent to serve the frontend and reverse-proxy the API
- systemd-managed services or an appropriate container deployment approach

Choose whichever deployment architecture works most reliably inside Proxmox LXC.

Avoid unnecessary privileged LXC configurations.

Do not assume Docker-in-LXC is necessary. A conventional systemd deployment is perfectly acceptable and may be preferable.

Inspect available Proxmox storage, container templates, and unused CT IDs before provisioning.

Do not modify, overwrite, or destroy existing containers, VMs, storage, or unrelated services.

Suggested initial resources:
2 vCPUs
4 GB RAM
24 GB disk

Adjust only if there is a good reason.

Make deployments reproducible and idempotent.

Include:
- Installation scripts
- Deployment scripts
- Environment configuration
- Database migration support
- Service management
- Backup and restoration instructions
- Proper logging
- Health checks
- Restart on failure
- Update procedure

Do not expose PostgreSQL directly to the internet.

Do not commit passwords, credentials, private keys, or secrets to Git.

============================================================
3. PRODUCT DATABASE AND DANISH BARCODE SUPPORT
============================================================

This is one of the most important parts of the entire project.

PantryNanny must maintain its own permanent PostgreSQL product catalogue.

The catalogue should progressively improve as we scan products.

Danish supermarket products are especially important, including:

- Netto
- Føtex
- Bilka
- REMA 1000
- Lidl
- Coop
- SuperBrugsen
- Kvickly
- 365discount
- Meny
- Spar
- Other Danish and European brands

Implement a product identification pipeline.

PRIMARY SOURCE:
Open Food Facts

Investigate its current API, available datasets, rate limits, licensing, and Danish product coverage.

SECONDARY SOURCES:
Investigate whether legitimate and usable product information is available through:

- GS1 Denmark
- Salling Group APIs
- EAN-Search
- Other relevant publicly accessible Danish product sources

Only implement providers that actually offer suitable and legally usable access.

Do not assume commercial databases are freely accessible.

Do not implement unauthorized scraping or bypass rate limits and access controls.

Design the provider system as modular adapters so more sources can be added later.

Product lookup priority:

1. Local phone/tablet cache
2. PantryNanny's own PostgreSQL product catalogue
3. External product information providers
4. User-assisted creation if no match exists

Product data should include where available:

- Barcode / GTIN / EAN
- Product name
- Brand
- Category
- Product image
- Package size
- Quantity and unit
- Ingredients
- Allergens
- Nutritional information
- Product description
- Country or market
- Source provider
- Source attribution/license
- Last updated timestamp
- Lookup confidence

Support EAN-13, EAN-8, UPC-A, and other common retail barcode formats.

Normalize barcode identifiers carefully while preserving original scanned values.

VERY IMPORTANT:
Once a product has been recognized, it must remain available in our own database regardless of whether the external provider is accessible later.

User corrections and custom product information should take precedence over scraped/imported information.

External provider refreshes must never silently overwrite household corrections.

Store attribution, licensing, provenance, and lookup history appropriately.

Unknown products must NOT interrupt the grocery scanning workflow.

For an unknown barcode:
- Save the barcode immediately.
- Create a temporary placeholder product.
- Permit scanning to continue.
- Attempt background identification.
- Allow the user to resolve unknown products afterward.

Implement an extremely simple unknown-product editor.

Ideally allow:
- Photographing the package
- OCR-assisted name recognition where practical
- Manual product name entry
- Category selection
- Package quantity
- Save

A newly registered barcode should be recognized instantly on subsequent scans.

Provide an administration interface showing:
- Recognized products
- Unknown products
- Products needing review
- Source information
- Failed lookups
- Duplicate candidates
- Lookup statistics

Consider a background catalogue-enrichment task for unresolved products, with appropriate rate limiting.

Don't download enormous external datasets onto phones. Cache the relevant household catalogue and recently used products instead.

============================================================
4. POSTGRESQL DATABASE AND INVENTORY MODEL
============================================================

Design a clean, maintainable database schema with migrations.

Separate the concept of PRODUCTS from INVENTORY.

A product represents what an item is.

An inventory record represents how much of that product we currently have and where it is stored.

Required concepts:

PRODUCTS
Shared product catalogue containing identifiers and metadata.

INVENTORY
Current quantities for the household.

LOCATIONS
Examples:
- Fridge
- Freezer
- Pantry
- Kitchen cupboard
- Other/custom locations

STOCK TRANSACTIONS
Every inventory change should be represented by an auditable transaction.

Examples:
- Added 3 cartons of milk
- Removed 1 carton
- Adjusted quantity
- Moved an item to the freezer
- Corrected a scanning mistake

HOUSEHOLD USERS
Multiple household members should share the same inventory.

EXPIRATION DATES
Optional expiration dates and per-batch tracking where appropriate.

SHOPPING LIST
Shared shopping list with quantities and checkable items.

PRODUCT LOOKUP CACHE
External lookup results, failures, and refresh metadata.

UNKNOWN PRODUCTS
Items awaiting recognition or manual classification.

DESIGN REQUIREMENTS:

- Support quantities as integers and decimals where appropriate.
- Support units such as pieces, grams, kilograms, ml, liters, packages, etc.
- Avoid mixing package counts with product contents.
- Support multiple batches of the same product with different expiration dates.
- Support configurable minimum stock levels.
- Support product aliases and household-specific names.
- Support soft deletion where appropriate.
- Maintain a useful audit trail.
- Support multiple simultaneous users.
- Prevent double counting from synchronization retries.
- Provide clean migration and backup strategies.

Use stable unique IDs and idempotent inventory operations.

Inventory synchronization must be robust when multiple devices scan products concurrently.

Favor a transaction-based approach rather than simply overwriting inventory quantities from different clients.

============================================================
5. WEB APPLICATION
============================================================

Build a polished, modern, bright, inviting, and genuinely useful web application.

URL:
https://pantry.example.com

Backend port:
8734

The design should feel like a modern consumer application rather than an old enterprise inventory system.

Design direction:
- Bright and friendly
- Clean typography
- Warm but restrained color palette
- Modern cards and layouts
- Smooth, subtle animations
- Clear icons
- Good whitespace
- Accessible controls
- Fast navigation
- Excellent mobile responsiveness
- Danish language by default
- English language support desirable

Do not make the interface overly childish or gimmicky.

Use a consistent design system.

Recommended frontend stack:
React
TypeScript
Vite
Tailwind CSS or equivalent
Modern accessible UI components

Use established libraries where they meaningfully improve quality.

MAIN DASHBOARD

Provide a useful overview:

- Total products in stock
- Products running low
- Products expiring soon
- Products already expired
- Recently added products
- Recently consumed products
- Products needing identification
- Shopping list overview
- Inventory organized by location

The interface should make it immediately obvious what we have in the kitchen.

INVENTORY MANAGEMENT

Provide:
- Search
- Filter by location
- Filter by category
- Sort by name, quantity, expiry, etc.
- Product photos
- Inline quantity adjustment
- Add/remove actions
- Move between locations
- Bulk editing
- Expiration date editing
- Product detail views
- Transaction history
- Manual inventory corrections

SEARCH

Search should be fast and forgiving.

Support:
- Danish product names
- Brands
- Categories
- Barcodes
- Partial matches
- Product aliases

SHOPPING LIST

Implement a practical shared shopping list.

Allow:
- Manual addition
- Addition from inventory
- Suggested additions for low-stock items
- Quantity editing
- Checking off products
- Removing completed entries
- Grouping by category
- Exporting or copying the list

EXPORT

Users must be able to export:
- Complete inventory
- Shopping list
- Expiring products
- Product catalogue
- Transaction history where useful

Support CSV and JSON at minimum.

Make exports usable in Excel and other tools, including proper UTF-8 handling for Danish characters.

DATABASE MANAGEMENT

Provide a sensible administration area to:
- Edit known products
- Resolve unknown products
- Manage categories
- Manage locations
- Configure stock thresholds
- Review barcode lookup failures
- Configure external lookup providers
- Manage application settings

============================================================
6. IPAD WALL-MOUNTED PWA
============================================================

THIS IS A CRITICAL FEATURE.

We have an iPad mounted on the wall next to the refrigerator.

We do not want to build a native iOS application.

Instead, implement an excellent browser-based scanning interface that works on iPad Safari and preferably as an installable home-screen PWA.

The iPad will normally stay in the kitchen and be used as a convenient scanning station.

The desired workflow:

1. Open PantryNanny.
2. Select "ADD" mode.
3. Point products at the iPad camera.
4. Every successfully scanned product is automatically added.
5. Continue scanning additional products.
6. No further taps or confirmations should be required for recognized products.

The user should be able to scan an entire bag of groceries without interacting with the screen after entering scanning mode.

REMOVE MODE:

The same scanner must support removing items.

One prominent control should switch between:

ADD
REMOVE

The active mode must be EXTREMELY obvious.

Use different visual treatments for the two modes.

For example:
ADD: green visual accents
REMOVE: orange/red visual accents

Keep the camera running while scanning.

Do not require opening a camera dialog or confirming a scan for each item.

TECHNICAL REQUIREMENTS:

Investigate current iPadOS Safari camera, PWA, and barcode detection support.

Implement a browser-compatible barcode scanner using appropriate technologies such as ZXing, BarcodeDetector where supported, or another well-maintained library.

Do not assume Chrome-only APIs work in Safari.

Handle camera permissions correctly.

Support selecting the rear camera where possible.

Implement:
- Continuous scanning
- Autofocus where supported
- Scan detection feedback
- Visible last-scanned product
- Current quantity
- Recent scan history
- Undo last scan
- Large Add/Remove mode controls
- Offline operation
- Reconnection and synchronization
- Clear connection/sync status

BARCODE SCANNING BEHAVIOR:

A barcode that stays in view must not accidentally be counted repeatedly.

Implement reliable duplicate-frame suppression.

However, deliberately scanning multiple identical items must be easy.

For example:
Scan milk carton #1.
Remove it from view.
Scan milk carton #2.
Inventory should increase by another 1.

Use barcode disappearance/re-entry detection or another robust approach.

Don't impose an unnecessarily long cooldown that slows down scanning.

Different products should scan consecutively without artificial delays.

Provide audio and visual feedback.

Sound should be optional and respect browser limitations around audio initialization.

Use vibration/haptics where the platform supports it, but do not depend on it.

Display an easily recognizable success indicator and product name.

UNKNOWN BARCODES:

Never stop the scanning session.

Record the barcode and transaction, show a nonblocking notification, and continue scanning.

Unknown items can be resolved later.

PWA CONSIDERATIONS:

Support:
- Home-screen installation
- Appropriate manifest
- Service worker
- Offline caching
- Responsive tablet layout
- Standalone display mode
- Large touch targets
- Stable screen orientation handling
- Reconnection

Investigate screen wake-lock support.

Where iPadOS restrictions make continuous wake-lock unavailable, document realistic alternatives such as iPad settings or Guided Access.

Be honest about platform limitations:
Opening the app or activating its camera may require an initial tap or permission grant.

The goal is ZERO additional interaction per recognized barcode once the scanner has started, not violating browser security restrictions.

The scanner must work over HTTPS through pantry.example.com.

Provide an optional dedicated kiosk/scanner route, for example:

https://pantry.example.com/scan

This should be optimized specifically for the wall-mounted iPad.

Allow the iPad to remain associated with a household scanning profile without repeatedly requiring login, while retaining sensible security controls.

============================================================
7. NATIVE ANDROID APPLICATION
============================================================

Build a proper Android application.

The Android app should be functional, fast, responsive, and reliable.

It does not need elaborate animations or unnecessary visual effects.

The primary goal is extremely fast barcode scanning.

Recommended implementation:
Kotlin
Jetpack Compose
CameraX
Google ML Kit barcode scanning or another suitable on-device barcode detector
Room/SQLite
WorkManager for background synchronization

You may choose a different approach if there is a compelling technical reason, but native Android scanning performance is a priority.

ANDROID APP FEATURES:

- Fast startup
- Very fast camera initialization
- Continuous scanning
- Add mode
- Remove mode
- Scan history
- Last scanned product
- Product details
- Inventory overview
- Search
- Basic inventory editing
- Offline operation
- Automatic background synchronization
- Shared household inventory
- Configurable backend URL
- Secure authentication
- Optional sound and vibration feedback

SCANNING EXPERIENCE:

The user should be able to open the app, tap Add, and scan groceries continuously.

Ideally remember the last selected scanning mode where appropriate, but avoid unsafe accidental Remove operations.

Recognized products should not require confirmation.

Unknown products should not block scanning.

The application should support scanning multiple identical products intentionally without accidentally counting the same barcode continuously while it remains in camera view.

Minimize latency.

Aim for:
- Immediate local recognition of cached barcodes
- Local inventory changes reflected in the UI within approximately 100–200 ms where practical
- Continuous scanning without waiting for network requests
- No unnecessary loading screens
- No dependency on internet connectivity during normal scanning

These are performance targets, not excuses to sacrifice correctness.

Use efficient camera analysis and avoid expensive operations on the UI thread.

Support offline-first operation.

Store all relevant household products locally.

Synchronize background changes with the backend when available.

Do not download the entire global Open Food Facts database to the phone.

Deliver a buildable Android Studio project and, if the build environment supports it, a working debug APK.

If signing credentials are not available, document the release-signing procedure.

============================================================
8. OFFLINE-FIRST ARCHITECTURE
============================================================

Offline capability is essential, not optional.

Both Android and the PWA should remain useful if the backend or network is temporarily unavailable.

Implement a local product cache and a persistent operation queue.

Core principle:

A scan should update the local UI immediately and synchronize with the server independently.

Example:

User scans a product.
Barcode is recognized in local cache.
A local inventory operation is recorded.
The interface immediately confirms success.
The operation is transmitted to the server in the background.

If the server is unavailable:
- Keep the operation locally.
- Clearly indicate pending synchronization.
- Retry later.
- Never silently discard scanned inventory changes.

The server must accept idempotent operations.

Use unique client-generated operation IDs to prevent duplicate application of transactions during retries.

Handle:
- Interrupted uploads
- Network reconnection
- Duplicate retries
- Simultaneous household devices
- Client restarts
- Cached product updates
- Server-side product corrections

Make database writes transactional.

Define a clear conflict resolution strategy.

For inventory quantities, prefer additive stock transactions rather than last-write-wins replacement.

For editable metadata, document and implement sensible versioning/conflict handling.

PWA persistence should use IndexedDB or an appropriate established abstraction.

Android should use Room/SQLite.

Sync must work reliably in the foreground, and in the background where supported.

Do not assume iPadOS will run a service worker indefinitely while the app is suspended.

============================================================
9. LOCAL AI ASSISTANT
============================================================

We have an OpenAI-compatible AI endpoint available on our private network:

<openai-compatible-endpoint>/v1

Implement OPTIONAL AI functionality using this endpoint.

The endpoint should be configurable through environment variables or administration settings.

Do not hardcode API credentials.

The backend should communicate with the AI service.

Browser and mobile clients should communicate with PantryNanny's backend rather than directly with the model endpoint.

Investigate available models through the endpoint if possible.

Do not assume a specific model name.

If the endpoint is unavailable, the rest of PantryNanny must continue functioning normally.

AI FEATURES:

Implement a simple conversational assistant accessible from the web interface.

Example questions:

"What do we have in the fridge?"

"Do we have enough ingredients to make lasagna?"

"What could we cook tonight with what we already have?"

"Which products expire in the next three days?"

"What groceries should we buy?"

"Suggest three dinner ideas using ingredients we already have."

"Do we have any milk left?"

"Which ingredients are running low?"

The assistant must have access to actual inventory information.

Do not simply send a vague prompt asking the AI to guess our pantry contents.

Implement structured tool/function calling or another safe backend mechanism that allows the AI assistant to retrieve actual inventory data.

Useful tools might include:
- search_inventory
- list_inventory_by_location
- list_expiring_products
- get_product_details
- get_low_stock_items
- get_shopping_list

Ensure AI queries use actual current database state.

Never allow the model to execute unrestricted SQL.

Use validated, read-only database query functions.

Treat product names and imported descriptions as untrusted data to guard against prompt injection.

For the initial version, AI functionality should be read-only.

Do not allow the AI to remove inventory, modify shopping lists, or perform destructive operations without a separately designed confirmation workflow.

Make AI functionality optional and cleanly separated from core inventory operations.

BONUS:
Add a recipe suggestion interface that uses available ingredients and clearly distinguishes between:
- Ingredients we have
- Ingredients we are missing
- Optional substitutions

Do not let the AI assistant become a dependency of normal scanning.

============================================================
10. OTHER USEFUL FEATURES
============================================================

Implement sensible additional features where they improve the core experience.

PRIORITY FEATURES:

A. Expiration tracking

Allow expiration dates to be added to inventory batches.

Show:
- Expiring soon
- Already expired
- Products that should be consumed first

Make expiration entry optional during normal scanning.

Never require users to input an expiry date for every barcode scan.

B. Shopping list automation

Allow configuring minimum quantities.

When an inventory item drops below its threshold, suggest adding it to the shopping list.

Avoid duplicate shopping-list entries.

C. Categories and locations

Support custom categories and storage locations.

Allow default storage locations per product.

D. Inventory corrections

Make it extremely easy to correct a mistake.

Provide Undo after scanning.

E. Product images

Cache suitable product images when permitted.

Provide a placeholder image where none exists.

F. Household sharing

The server should support multiple users/devices sharing one household inventory.

G. Useful statistics

Show basic trends such as:
- Most frequently added products
- Most frequently consumed products
- Recently added products
- Product quantities over time

Do not make elaborate reporting a priority over core functionality.

FUTURE-FRIENDLY:

Design the backend with a clean API so Home Assistant integration can be added later.

If straightforward, provide a documented read-only Home Assistant-compatible REST integration.

Do not let Home Assistant integration delay the main implementation.

============================================================
11. SECURITY AND RELIABILITY
============================================================

This is a household application accessible through our personal reverse proxy.

Implement appropriate security without making ordinary use cumbersome.

Requirements:
- Secure login/authentication
- Household user accounts
- Appropriate roles/permissions
- Secure password storage
- Protection against common web vulnerabilities
- Input validation
- API request authorization
- Safe file upload handling
- Sensible CORS configuration
- HTTPS-aware reverse proxy configuration
- Secrets via environment or protected configuration
- No exposed PostgreSQL port
- Rate limiting where appropriate
- Safe handling of external product data
- Backup/restore process

Do not expose the AI endpoint directly through the public web UI.

Support convenient long-lived sessions on trusted household devices.

Consider a restricted tablet/kiosk profile for the wall-mounted iPad.

Avoid frequent authentication interruptions during grocery scanning.

Provide health endpoints such as:
GET /api/health

Implement useful structured logs.

Avoid logging passwords, API keys, authentication tokens, or unnecessarily sensitive information.

BACKUPS:

Create a documented automated backup mechanism for PostgreSQL and relevant uploaded assets.

Use a reasonable retention policy.

Provide a tested restoration procedure.

Do not claim backups are working unless actually verified.

============================================================
12. API DESIGN
============================================================

Implement a documented REST API.

Use OpenAPI/Swagger documentation where practical.

Provide clean endpoints for:

Authentication
Households/users
Products
Barcode lookup
Product search
Inventory
Inventory transactions
Locations
Categories
Expiration dates
Shopping lists
Synchronization
Configuration
Health/status
AI assistant

Create a dedicated high-performance scanning endpoint or synchronization mechanism as appropriate.

Product scanning and stock changes must be properly separated conceptually.

A barcode lookup must not implicitly alter stock.

Only an explicit Add/Remove inventory operation should change stock.

Make the API usable by Android, the PWA, and potential future Home Assistant integrations.

Define request/response types clearly.

Avoid duplicating business logic between clients.

============================================================
13. USER EXPERIENCE PRIORITIES
============================================================

Prioritize these in this exact order:

1. Barcode scanning reliability
2. Fast, effortless Add/Remove workflow
3. Offline operation
4. Accurate synchronization
5. Danish product recognition
6. Easy handling of unknown products
7. Clear inventory overview
8. Modern, pleasant web design
9. Shopping lists and expiration tracking
10. AI functionality
11. Additional statistics and enhancements

Never compromise the core scanning experience to implement a decorative dashboard or secondary feature.

The application should be usable by someone who has no interest in technology.

Avoid:
- Unnecessary confirmation dialogs
- Too many mandatory fields
- Complicated product management screens
- Waiting for an API request after every scan
- Scanning modes that reset unexpectedly
- Repeated authentication prompts
- Slow transitions
- Tiny buttons on the iPad
- Accidental duplicate scans
- Silent failures

Aim for a delightful experience in which the technology disappears into the background.

============================================================
14. PROJECT STRUCTURE AND GITHUB
============================================================

Use the repository:

the project GitHub repository

Inspect the repository first.

If it is empty, initialize a clean monorepo structure.

Suggested structure:

pantrynanny/
  backend/
  web/
  android/
  deployment/
  scripts/
  docs/
  tests/
  README.md
  .gitignore
  .env.example

You may choose a better structure if justified.

Use:
- Clear code organization
- Sensible naming
- Type safety
- Database migrations
- Reusable components
- Environment-based configuration
- Meaningful logging
- Tests
- Automated formatting/linting
- Useful documentation

Commit work to Git regularly with meaningful commit messages.

Push completed work to the configured GitHub repository using available authorized SSH credentials.

Do not accidentally overwrite existing work.

Create a useful README documenting:
- What PantryNanny does
- Architecture
- Development setup
- Production deployment
- Android build instructions
- PWA installation
- WireGuard requirements
- Configuration
- External barcode providers
- AI integration
- Backup/restore
- Updating
- Troubleshooting

Provide a clear .env.example without real secrets.

============================================================
15. DEVELOPMENT AND EXECUTION STRATEGY
============================================================

Work autonomously.

Do not stop after producing an architecture proposal.

Actually implement the application.

Begin by inspecting the repository and available deployment environment.

Make reasonable decisions independently.

Use a staged implementation:

PHASE 1:
- Inspect repository and environment
- Establish architecture
- Create project structure
- Implement PostgreSQL schema and migrations
- Implement core backend API
- Implement product catalogue and inventory transactions

PHASE 2:
- Integrate Open Food Facts lookup
- Implement product caching
- Support manual and unknown product creation
- Build reliable stock transaction operations
- Implement basic authentication

PHASE 3:
- Build the responsive web application
- Implement inventory dashboard
- Implement product management
- Implement shopping lists
- Implement export functionality
- Implement expiration tracking

PHASE 4:
- Implement the continuous-scanning PWA
- Make iPad scanning fast and simple
- Implement IndexedDB caching
- Implement offline synchronization
- Test Safari compatibility as far as the environment allows

PHASE 5:
- Build the native Android application
- Implement fast camera scanning
- Implement local Room database
- Implement background synchronization
- Connect Android to the shared backend
- Build a debug APK if tooling permits

PHASE 6:
- Integrate the optional local AI endpoint
- Implement read-only inventory tools
- Implement conversational assistant
- Add recipe suggestions if feasible

PHASE 7:
- Deploy to Proxmox LXC
- Configure system services
- Configure port 8734
- Implement backups
- Run tests
- Verify services
- Update documentation
- Push repository changes

You may adjust the phase order when doing so improves development efficiency.

IMPORTANT:
Deliver working end-to-end vertical slices rather than implementing dozens of disconnected unfinished features.

Ensure the system is usable even if optional AI, OCR, or secondary barcode providers are unavailable.

============================================================
16. TESTING AND ACCEPTANCE CRITERIA
============================================================

Create meaningful automated tests.

At minimum test:

PRODUCT LOOKUP:
- Known barcode in local database
- Known barcode requiring external lookup
- Unknown barcode
- Unavailable external API
- Barcode normalization
- Manual product correction
- Cached lookup reuse

INVENTORY:
- Add one item
- Remove one item
- Add multiple identical items
- Prevent negative stock where configured
- Undo an operation
- Concurrent updates
- Idempotent retries
- Inventory adjustment
- Multiple storage locations

OFFLINE SYNC:
- Backend unavailable during scan
- Operations stored locally
- Reconnect
- Operations synchronize exactly once
- Multiple devices update the same product
- Restart client with pending operations

SCANNING:
- Continuous different-product scanning
- Multiple identical items
- Barcode held continuously in camera view
- Barcode exits and re-enters view
- Unknown barcode
- Switching Add/Remove modes
- Network failure during scanning

SECURITY:
- Unauthorized API access
- Household isolation
- Input validation
- Safe authentication handling
- No leaked credentials

WEB:
- Inventory management
- Shopping list
- Exports
- Mobile responsiveness
- Error handling

ANDROID:
- Build succeeds
- Scanner workflow
- Offline database
- Sync queue
- API compatibility

PWA:
- Build succeeds
- Service worker
- Offline data persistence
- Camera scanning
- Safari-compatible implementation

Where physical Android devices or iPads are unavailable, perform all feasible automated/browser tests and clearly document what requires real-device verification.

Do not claim that real-device performance has been verified unless it actually has.

PERFORMANCE:

Measure and optimize:
- Local barcode recognition latency
- Time to inventory update
- Camera scanning responsiveness
- API latency
- Product lookup cache hit rate
- Frontend initial load performance

Use realistic test data.

============================================================
17. DEPLOYMENT COMPLETION REQUIREMENTS
============================================================

When finished, the following should be true:

1. PantryNanny exists in the specified GitHub repository.

2. The new Proxmox LXC exists and is configured.

3. PostgreSQL is running and initialized.

4. Backend API is running.

5. Web interface is served on port 8734.

6. The service is prepared for the WireGuard IP <container-wireguard-ip>.

7. Once I configure WireGuard and Traefik, the web application should be reachable at:
   https://pantry.example.com

8. The website supports normal inventory management.

9. The PWA provides a practical continuous-scanning interface.

10. An Android app project is implemented and builds successfully.

11. The product catalogue supports Open Food Facts and locally saved products.

12. Scanning known products is fast and doesn't depend on a network request.

13. Unknown barcode handling is functional.

14. Offline inventory transactions synchronize reliably.

15. AI integration is available when the configured local endpoint is reachable.

16. Deployment and backup procedures are documented.

17. Tests have been executed, and their results are reported accurately.

If some functionality cannot be completed or verified because of missing physical devices, credentials, WireGuard setup, external API restrictions, or environmental limitations, document exactly what remains.

Do not present incomplete features as complete.

============================================================
18. FINAL DELIVERABLES
============================================================

At completion, provide:

A. GitHub repository status and latest commit.

B. Proxmox container:
   - CT ID
   - Hostname
   - Distribution
   - Resource allocation
   - Network configuration
   - WireGuard setup requirements

C. Service information:
   - Internal URL
   - External URL
   - API documentation URL
   - Health endpoint
   - Systemd service names
   - Relevant configuration locations

D. Authentication setup:
   - How to create the first admin user
   - How to add household users
   - How to configure trusted kiosk devices

E. Android:
   - Source location
   - Build instructions
   - Debug APK location, if produced
   - Installation instructions

F. iPad:
   - PWA URL
   - Installation instructions
   - Camera permission requirements
   - Recommended wall-mounted usage setup

G. Product catalogue:
   - Implemented data sources
   - Lookup strategy
   - Cache strategy
   - Known coverage limitations

H. AI:
   - Configuration
   - Detected/configured model
   - Available assistant capabilities

I. Maintenance:
   - Backup procedure
   - Restore procedure
   - Update procedure
   - Logs
   - Troubleshooting

J. Verification:
   - Tests executed
   - Tests passed
   - Outstanding limitations
   - Manual testing still required

============================================================
19. AUTONOMY AND IMPORTANT BOUNDARIES
============================================================

You have permission to implement the project, install necessary dependencies, create the new PantryNanny LXC, configure services inside it, and work with the specified GitHub repository.

Do not change unrelated Proxmox resources, existing virtual machines, other LXC containers, global network configuration, firewall rules, or existing services.

Do not delete existing infrastructure.

Do not configure or generate my WireGuard identity. I will handle that.

Do not modify my Traefik configuration. I will handle that.

When WireGuard becomes the only blocker to external connectivity, provide the needed setup information and continue with other work where possible.

Only request human intervention for genuine blockers, such as missing permissions, credentials, destructive infrastructure decisions, or the WireGuard connection I explicitly reserved for myself.

Do not repeatedly ask for design preferences.

Choose sensible modern defaults and implement them.

Do not use fake API responses or mock data in production workflows.

Do not silently substitute placeholder functionality for required features.

Prefer a working implementation over ambitious but unfinished abstractions.

============================================================
20. FINAL PRODUCT VISION
============================================================

PantryNanny should become the central inventory system for our kitchen.

It should feel like a modern, friendly household application.

The web interface should make it easy to understand what food we own, what needs to be used, and what needs to be bought.

The Android application should turn an ordinary smartphone into an exceptionally efficient grocery scanner.

The wall-mounted iPad should act as a permanent kitchen scanning station.

The local PostgreSQL product database should become more useful over time as it learns the products we buy.

External barcode databases should minimize manual work, not become a dependency for everyday operation.

The AI assistant should help us make intelligent use of our inventory without being necessary for basic functionality.

Above everything else:

A family member returning from the supermarket should be able to put away fifteen groceries, scan them as they go, and finish without feeling that keeping inventory has become another household chore.

That is the standard by which the design should be judged.

BEGIN IMPLEMENTATION NOW.

Inspect the repository and Proxmox environment, establish the architecture, and proceed through implementation, testing, deployment, documentation, and GitHub delivery.

Do not stop at planning.
Build PantryNanny.

```
