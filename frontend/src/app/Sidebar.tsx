// Workspace sidebar: brand, repository card, page navigation, Markdown source controls, agent access, and settings.
import { useState } from 'react'
import { Activity, ArrowUpRight, ChevronDown, Database, FileText, GitBranch, GitFork, GitPullRequest, LoaderCircle, Network, Plus, Search, Settings2, Sparkles, TerminalSquare } from 'lucide-react'
import { PRODUCT_NAME } from '../brand'
import type { ScanState } from '../features/discovery/scanState'
import type { Page } from './navigation'
import { Button } from '../components/ui/button'

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
    <div className="brand"><div className="brand-icon"><GitBranch size={17} /></div><span>{PRODUCT_NAME}</span><Button variant="icon" size="icon" className="workspace-switch"><ChevronDown size={14} /></Button></div>
    <Button variant="ghost" className="repo-card" onClick={() => void openRepositoryChooser()} title={projectRoot || 'Open a repository mounted by the backend'}><div className="repo-icon"><GitFork size={15} /></div><div><strong>{projectName}</strong><span>{live ? projectRoot || 'Mounted repository' : 'Sample · click to open repository'}</span></div><span className="repo-open-label">Open repository</span></Button>
    <div className="nav-label">WORKSPACE</div>
    <nav className="main-nav" aria-label="Workspace pages">
      {[[Network, 'Architecture'], [FileText, 'Architecture log'], [Activity, 'Progress'], [Database, 'Facts'], [GitPullRequest, 'Scenarios'], [Search, 'Explore']].map(([Icon, label]) => <Button variant="ghost" key={String(label)} className={`nav-item ${activeNav === label ? 'active' : ''}`} aria-label={String(label)} aria-current={activeNav === label ? 'page' : undefined} onClick={() => navigateTo(String(label) as Page)}><Icon size={16} /><span className="nav-item-label"><span className="nav-label-full">{String(label)}</span><span className="nav-label-short">{label === 'Architecture' ? 'Map' : label === 'Architecture log' ? 'Log' : label === 'Scenarios' ? 'Scenario' : String(label)}</span></span>{label === 'Facts' && pendingCount > 0 && <span className="nav-badge">{pendingCount}</span>}</Button>)}
    </nav>
    <div className="nav-label sources-label">SOURCE TYPES <Button variant="ghost" className="tiny-icon min-h-0" aria-label="Toggle source controls" aria-expanded={sourceControlsOpen} onClick={() => setSourceControlsOpen((open) => !open)}><Plus size={13} /></Button></div>
    {sourceControlsOpen && <div className="source-controls"><div className="source-type"><span className="source-dot green" /><strong>Markdown</strong><span>V0 supported</span></div><p>Discover decisions and evidence from Markdown files in this repository.</p><Button variant="ghost" className="source-discover min-h-0" disabled={scanState === 'scanning'} onClick={beginDiscover}>{scanState === 'scanning' ? <LoaderCircle className="spin" size={12} /> : <Sparkles size={12} />}{scanState === 'scanning' ? 'Discovering…' : 'Discover / Scan'}</Button>{scanSummary && <div className={`source-scan-result ${scanState === 'error' || scanState === 'refresh-error' ? 'error' : ''}`} role={scanState === 'error' || scanState === 'refresh-error' ? 'alert' : 'status'}>{scanSummary}</div>}</div>}
    <div className="sidebar-spacer" />
    <Button variant="ghost" className="mcp-callout min-h-auto" onClick={() => navigateTo('Explore')}><div className="mcp-icon"><TerminalSquare size={15} /></div><div><strong>Agent access</strong><span>{live ? 'Backend MCP endpoint' : 'Connect backend for MCP'}</span></div><ArrowUpRight size={14} /></Button>
    <Button variant="ghost" className="profile min-h-auto" onClick={() => onOpenSettings()}><div><strong>Workspace settings</strong><span>Local · private</span></div><Settings2 size={15} /></Button>
  </aside>
}
