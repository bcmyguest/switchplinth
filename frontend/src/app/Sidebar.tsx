// Workspace sidebar: brand, repository card, page navigation, Markdown source controls, agent access, and settings.
import { useState } from 'react'
import { Activity, ArrowUpRight, Database, FileText, GitBranch, GitFork, GitPullRequest, LoaderCircle, Network, Plus, Search, Settings2, Sparkles, TerminalSquare } from 'lucide-react'
import { PRODUCT_NAME } from '../brand'
import type { ScanState } from '../features/discovery/scanState'
import type { Page } from './navigation'
import { Button } from '../components/ui/button'

/** Sidebar chrome classes; the `max-sm:` variants are the mobile top-bar layout. */
const REPO_CARD = "mb-[24px] flex min-h-[48px] w-full min-[1025px]:flex-wrap items-center justify-start gap-[9px] rounded-[9px] border border-(--theme-line) bg-(--theme-panel) p-[9px] text-left shadow-[0_1px_2px_#17271905] hover:bg-(--theme-hover) max-sm:m-0 max-sm:min-w-0 max-sm:px-[8px] max-sm:py-[6px]"
const REPO_TEXT = "flex min-w-0 flex-1 flex-col min-[1025px]:flex-[1_1_calc(100%_-_40px)] gap-[2px] [&>span]:truncate [&>span]:text-(length:--type-tertiary) [&>span]:text-(--theme-muted) [&>strong]:truncate [&>strong]:text-(length:--type-secondary) [&>strong]:font-[650] [&>strong]:text-(--theme-ink)"
const REPO_OPEN = "ml-auto inline-flex min-h-(--control-target) items-center rounded-[4px] border border-(--theme-line) bg-(--theme-panel-raised) px-[8px] py-[4px] text-(length:--type-tertiary) whitespace-nowrap text-(--theme-source)"
const NAV_ITEM = "relative flex min-h-(--control-target) items-center justify-start gap-[10px] rounded-[7px] px-[10px] text-left text-(length:--type-secondary) text-(--theme-ink) hover:bg-(--theme-hover) [&>svg]:text-(--theme-muted) aria-[current=page]:bg-(--theme-brand-soft) aria-[current=page]:font-semibold aria-[current=page]:text-(--theme-source) aria-[current=page]:[&>svg]:text-(--theme-source) max-sm:h-[44px] max-sm:min-w-0 max-sm:flex-1 max-sm:flex-col max-sm:justify-center max-sm:gap-[2px] max-sm:px-[1px] max-sm:py-[3px] max-sm:text-(length:--type-tertiary) max-sm:[&>svg]:size-[15px]"
const NAV_BADGE = "ml-auto rounded-[5px] bg-[#fbefe0] px-[5px] py-[2px] font-['DM_Mono',monospace] text-(length:--type-caption) text-(--theme-warning) dark:bg-[#3a2f1d] max-sm:absolute max-sm:top-0 max-sm:right-[4px] max-sm:m-0 max-sm:px-[4px] max-sm:py-[1px]"

type SidebarProps = {
  activeNav: Page
  navigateTo: (page: Page) => void
  projectName: string
  projectRoot: string
  live: boolean
  pendingCount: number
  scanState: ScanState
  scanSummary: string
  onOpenRepository: () => void
  onOpenSettings: () => void
  onDiscover: () => void
}

export function Sidebar({ activeNav, navigateTo, projectName, projectRoot, live, pendingCount, scanState, scanSummary, onOpenRepository: openRepositoryChooser, onOpenSettings, onDiscover: beginDiscover }: SidebarProps) {
  const [sourceControlsOpen, setSourceControlsOpen] = useState(false)
  return <aside className="sidebar">
    <div className="brand"><div className="brand-icon"><GitBranch size={17} /></div><span>{PRODUCT_NAME}</span></div>
    <Button variant="ghost" className={REPO_CARD} onClick={() => void openRepositoryChooser()} title={projectRoot || 'Open a repository mounted by the backend'}><div className="grid size-[26px] place-items-center rounded-[7px] bg-(--theme-panel-raised) text-(--theme-source)"><GitFork size={15} /></div><div className={REPO_TEXT}><strong>{projectName}</strong><span>{live ? projectRoot || 'Mounted repository' : 'Sample · click to open repository'}</span></div><span className={REPO_OPEN}>Open repository</span></Button>
    <div className="nav-label">WORKSPACE</div>
    <nav className="grid gap-[2px] max-sm:flex max-sm:w-full max-sm:justify-between" aria-label="Workspace pages">
      {[[Network, 'Architecture'], [FileText, 'Architecture log'], [Activity, 'Progress'], [Database, 'Facts'], [GitPullRequest, 'Scenarios'], [Search, 'Explore']].map(([Icon, label]) => <Button variant="ghost" key={String(label)} className={NAV_ITEM} aria-label={String(label)} aria-current={activeNav === label ? 'page' : undefined} onClick={() => navigateTo(String(label) as Page)}><Icon size={16} /><span className="max-sm:max-w-full max-sm:overflow-hidden max-sm:text-ellipsis max-sm:whitespace-nowrap"><span className="max-sm:hidden">{String(label)}</span><span className="hidden max-sm:inline max-sm:max-w-full max-sm:overflow-hidden max-sm:text-ellipsis max-sm:whitespace-nowrap">{label === 'Architecture' ? 'Map' : label === 'Architecture log' ? 'Log' : label === 'Scenarios' ? 'Scenario' : String(label)}</span></span>{label === 'Facts' && pendingCount > 0 && <span className={NAV_BADGE}>{pendingCount}</span>}</Button>)}
    </nav>
    <div className="nav-label sources-label">SOURCE TYPES <Button variant="ghost" className="tiny-icon min-h-0" aria-label="Toggle source controls" aria-expanded={sourceControlsOpen} onClick={() => setSourceControlsOpen((open) => !open)}><Plus size={13} /></Button></div>
    {sourceControlsOpen && <div className="source-controls"><div className="source-type"><span className="source-dot green" /><strong>Markdown</strong><span>V0 supported</span></div><p>Discover decisions and evidence from Markdown files in this repository.</p><Button variant="ghost" className="source-discover min-h-0" disabled={scanState === 'scanning'} onClick={beginDiscover}>{scanState === 'scanning' ? <LoaderCircle className="spin" size={12} /> : <Sparkles size={12} />}{scanState === 'scanning' ? 'Discovering…' : 'Discover / Scan'}</Button>{scanSummary && <div className={`source-scan-result ${scanState === 'error' || scanState === 'refresh-error' ? 'error' : ''}`} role={scanState === 'error' || scanState === 'refresh-error' ? 'alert' : 'status'}>{scanSummary}</div>}</div>}
    <div className="sidebar-spacer" />
    <Button variant="ghost" className="mcp-callout min-h-auto" onClick={() => navigateTo('Explore')}><div className="mcp-icon"><TerminalSquare size={15} /></div><div><strong>Agent access</strong><span>{live ? 'Backend MCP endpoint' : 'Connect backend for MCP'}</span></div><ArrowUpRight size={14} /></Button>
    <Button variant="ghost" className="profile min-h-auto" onClick={() => onOpenSettings()}><div><strong>Workspace settings</strong><span>Local · private</span></div><Settings2 size={15} /></Button>
  </aside>
}
