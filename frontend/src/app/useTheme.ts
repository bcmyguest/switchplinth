// Light/dark theme: starts from the saved preference, mirrors the choice to `<html data-theme>`, and saves each change.
import { useEffect, useState } from 'react'
import { readSavedTheme, saveTheme, type AppTheme } from '../theme-preference'

export function useTheme() {
  const [theme, setTheme] = useState<AppTheme>(readSavedTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    saveTheme(theme)
  }, [theme])

  return [theme, setTheme] as const
}
