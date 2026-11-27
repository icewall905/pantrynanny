# PantryNanny recipe import (browser extension)

Toolbar button and right-click menu that send the page you are on to PantryNanny's
"Import a recipe" reader. PantryNanny opens with the recipe filled in for review; nothing is
saved until you press Save. Works in Chrome/Edge/Brave and Firefox (121+), Manifest V3.

The extension keeps only your PantryNanny address (set on first install, or in its options).
It uses your normal login in the browser and has no access to page contents.

The web app's build packs this folder into `web/public/downloads/pantrynanny-recipe-import.zip`
(`web/scripts/pack-extension.mjs`); the Recipes page links to it.

- **Chrome/Edge/Brave**: unzip, open `chrome://extensions`, turn on Developer mode,
  "Load unpacked", pick the folder.
- **Firefox**: open `about:debugging#/runtime/this-firefox`, "Load Temporary Add-on", pick
  `manifest.json` (temporary until restart; a permanent install needs the add-on signed).
