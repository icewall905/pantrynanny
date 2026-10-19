import { useState } from 'react'
import { cn, hashIndex } from '../lib/format'

const tints = [
  'bg-leaf-100 text-leaf-700',
  'bg-honey-50 text-honey-600',
  'bg-tomato-100 text-tomato-600',
  'bg-sky-500/15 text-sky-500',
  'bg-cream-200 text-ink-700',
]

export function ProductThumb({
  name,
  src,
  className,
}: {
  name: string
  src?: string | null
  className?: string
}) {
  const [failed, setFailed] = useState(false)
  if (src && !failed) {
    return (
      <img
        src={src}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className={cn('size-14 shrink-0 rounded-2xl bg-cream-100 object-contain', className)}
      />
    )
  }
  const initial = (name.trim()[0] ?? '?').toUpperCase()
  return (
    <div
      aria-hidden
      className={cn(
        'grid size-14 shrink-0 place-items-center rounded-2xl text-xl font-extrabold',
        tints[hashIndex(name, tints.length)],
        className,
      )}
    >
      {initial}
    </div>
  )
}
