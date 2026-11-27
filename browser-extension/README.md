# PantryNanny recipe import (browser extension)

Toolbar button and right-click menu that save the recipe on the page you are on straight into
PantryNanny and open it there. The recipe data (schema.org JSON-LD) is read from the page as
the browser shows it and sent to `POST /api/recipes/import/save`, so sites that block servers
still work; for a right-clicked link the server reads the page itself. A page that is already
saved opens the existing recipe instead of saving it twice. Chrome/Edge/Brave and Firefox 128+,
Manifest V3.

Settings (open by themselves after install): PantryNanny address, username and password. The
password is used once to get a device token (`POST /api/auth/token`) and is not stored; the
token is revoked with "Log out" or under Admin → Devices. The extension asks for permission
to reach that one address and reads a page only when you click the button.

The web app's build packs this folder into `web/public/downloads/pantrynanny-recipe-import.zip`
(`web/scripts/pack-extension.mjs`); Recipes → "Browser extension" links it.

- **Chrome/Edge/Brave**: unzip, open `chrome://extensions`, turn on Developer mode,
  "Load unpacked", pick the folder.
- **Firefox**: open `about:debugging#/runtime/this-firefox`, "Load Temporary Add-on", pick
  `manifest.json` (temporary until restart; a permanent install needs the add-on signed).
