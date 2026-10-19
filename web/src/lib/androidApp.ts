import { useQuery } from '@tanstack/react-query'

/** Written by deployment/deploy.sh next to /downloads/pantrynanny.apk. */
export interface AndroidAppInfo {
  version_name: string
  version_code: number
  variant: 'debug' | 'release'
  commit: string
  built: string
  size: number
  sha256: string
}

export const ANDROID_APK_URL = '/downloads/pantrynanny.apk'

async function fetchInfo(): Promise<AndroidAppInfo | null> {
  const r = await fetch('/downloads/android.json', { cache: 'no-store' })
  if (!r.ok) return null // no APK deployed yet
  const ct = r.headers.get('content-type') ?? ''
  if (!ct.includes('json')) return null // e.g. the SPA shell from a dev server
  return (await r.json()) as AndroidAppInfo
}

/** Info about the deployed Android APK; `data` is null when none is published. */
export function useAndroidApp() {
  return useQuery({ queryKey: ['android-app'], queryFn: fetchInfo, staleTime: 5 * 60_000, retry: false })
}
