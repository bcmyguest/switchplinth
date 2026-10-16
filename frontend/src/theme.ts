import { parse } from 'yaml'
import themeSource from '../theme.yml?raw'

type ThemeConfig = { theme?: { color?: Record<string, string> } }

const themeConfig = parse(themeSource) as ThemeConfig

export function applyTheme() {
  const colors = themeConfig.theme?.color ?? {}
  for (const [name, value] of Object.entries(colors)) {
    document.documentElement.style.setProperty(`--${name}`, value)
  }
}
