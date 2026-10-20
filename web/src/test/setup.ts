import '@testing-library/jest-dom/vitest'
import 'fake-indexeddb/auto'

import { configure } from '@testing-library/react'
// findBy*/waitFor: tolerate a loaded machine (default 1 s is too tight next to the decoder tests)
configure({ asyncUtilTimeout: 4000 })
