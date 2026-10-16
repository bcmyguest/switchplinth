import { STORAGE_PREFIX } from './brand'

export type AppTheme = 'light' | 'dark'

const THEME_STORAGE_KEY = `${STORAGE_PREFIX}-theme`
// Keys written under former product names; read once and migrated to THEME_STORAGE_KEY.
const LEGACY_THEME_STORAGE_KEYS = ['waypoint-theme']

/** Return the saved theme, migrating a legacy key on first read. Storage failures fall back to light. */
export function readSavedTheme(): AppTheme {
  try {
    const storage = window.localStorage
    let saved = storage.getItem(THEME_STORAGE_KEY)
    if (saved === null) {
      const legacyKey = LEGACY_THEME_STORAGE_KEYS.find((key) => storage.getItem(key) !== null)
      if (legacyKey) {
        saved = storage.getItem(legacyKey)
        if (saved !== null) storage.setItem(THEME_STORAGE_KEY, saved)
        storage.removeItem(legacyKey)
      }
    }
    return saved === 'dark' ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

/** Persist the theme; when storage is unavailable the choice lasts for this session only. */
export function saveTheme(theme: AppTheme) {
  try { window.localStorage.setItem(THEME_STORAGE_KEY, theme) } catch { /* Session-only theme when storage is unavailable. */ }
}
