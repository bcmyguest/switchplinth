// Top bar: breadcrumbs, backend status, theme toggle, and the active model connection chip.
import { ChevronDown, ChevronRight, GitBranch, Moon, Sparkles, Sun } from 'lucide-react'
import { Button } from '../components/ui/button'
import type { AppTheme } from '../theme-preference'
import type { Connection } from '../types'
import type { Page } from './navigation'

type TopbarProps = {
  projectName: string
  activeNav: Page
  live: boolean
  theme: AppTheme
  onToggleTheme: () => void
  activeConnection: Connection | undefined
  onOpenSettings: () => void
}

export function Topbar({ projectName, activeNav, live, theme, onToggleTheme, activeConnection, onOpenSettings }: TopbarProps) {
  return <header className="topbar">
    <div className="breadcrumbs"><span>{projectName}</span><ChevronRight size={13} /><strong>{activeNav}</strong><span className="branch-pill"><GitBranch size={12} /> main</span></div>
    <div className="top-actions"><span className={`sync-pill ${live ? 'live' : ''}`}><span className="status-dot" />{live ? 'Backend connected' : 'Demo data · backend offline'}</span><Button type="button" variant="secondary" size="sm" className="theme-toggle" aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`} aria-pressed={theme === 'dark'} onClick={() => onToggleTheme()}>{theme === 'dark' ? <Sun size={15} /> : <Moon size={15} />}<span>{theme === 'dark' ? 'Light' : 'Dark'} theme</span></Button><Button variant="subtle" className="gap-[6px] px-[7px] font-normal max-sm:max-w-[145px] max-sm:overflow-hidden [&>svg]:text-(--theme-muted)" onClick={() => onOpenSettings()}><span className="grid size-[17px] place-items-center rounded-[5px] bg-[#f2eafa] text-[#8967a8] dark:bg-(--theme-brand-soft) dark:text-(--theme-brand)"><Sparkles size={12} /></span><span>{activeConnection?.model ?? activeConnection?.name ?? 'Add model'}</span><ChevronDown size={13} /></Button></div>
  </header>
}
