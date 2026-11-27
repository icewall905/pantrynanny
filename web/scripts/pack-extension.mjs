// Packs ../browser-extension into public/downloads/pantrynanny-recipe-import.zip (no deps:
// a minimal deflate zip writer). Runs before `vite` / `vite build`.
import { mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { crc32, deflateRawSync } from 'node:zlib'

const here = dirname(fileURLToPath(import.meta.url))
const src = join(here, '..', '..', 'browser-extension')
const out = join(here, '..', 'public', 'downloads', 'pantrynanny-recipe-import.zip')

const files = readdirSync(src).filter((f) => f !== 'README.md').sort()
const local = []
const central = []
let offset = 0
for (const name of files) {
  const data = readFileSync(join(src, name))
  const packed = deflateRawSync(data, { level: 9 })
  const nameBuf = Buffer.from(name)
  const crc = crc32(data)
  const head = Buffer.alloc(30)
  head.writeUInt32LE(0x04034b50, 0)
  head.writeUInt16LE(20, 4) // version needed
  head.writeUInt16LE(0x0800, 6) // utf-8 names
  head.writeUInt16LE(8, 8) // deflate
  head.writeUInt32LE(0x00210000, 10) // fixed time/date (1980-01-01) so builds are reproducible
  head.writeUInt32LE(crc, 14)
  head.writeUInt32LE(packed.length, 18)
  head.writeUInt32LE(data.length, 22)
  head.writeUInt16LE(nameBuf.length, 26)
  local.push(head, nameBuf, packed)
  const dir = Buffer.alloc(46)
  dir.writeUInt32LE(0x02014b50, 0)
  dir.writeUInt16LE(20, 4)
  dir.writeUInt16LE(20, 6)
  head.copy(dir, 8, 6, 30) // flags .. name length are laid out the same
  dir.writeUInt32LE(offset, 42)
  central.push(dir, nameBuf)
  offset += head.length + nameBuf.length + packed.length
}
const cd = Buffer.concat(central)
const end = Buffer.alloc(22)
end.writeUInt32LE(0x06054b50, 0)
end.writeUInt16LE(files.length, 8)
end.writeUInt16LE(files.length, 10)
end.writeUInt32LE(cd.length, 12)
end.writeUInt32LE(offset, 16)
mkdirSync(dirname(out), { recursive: true })
writeFileSync(out, Buffer.concat([...local, cd, end]))
console.log(`packed ${files.length} files -> ${out}`)
