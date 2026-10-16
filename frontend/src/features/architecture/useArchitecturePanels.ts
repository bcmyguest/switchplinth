// Architecture overlay panels: which overlay is open (component detail, What-if, or the option editor), the element that
// regains focus when it closes, first-control focus on open, Escape, and the backdrop close. The state lives in
// `useArchitecturePanelHost` because the delta editor opens and closes its own panel; `useArchitecturePanels` adds the
// behavior once the editor exists and closes the editor panel through `editor.close()`.
import { useEffect, useRef, useState, type Dispatch, type RefObject, type SetStateAction } from 'react'

export type ArchitecturePanel = 'detail' | 'editor' | 'scenario'

export type ArchitecturePanelHost = {
  panel: ArchitecturePanel | null
  setPanel: Dispatch<SetStateAction<ArchitecturePanel | null>>
  /** The open panel's root element; its first enabled control receives focus when a panel opens. */
  panelRef: RefObject<HTMLElement | null>
  /** The element that receives focus when the overlay closes. */
  openerRef: RefObject<HTMLElement | null>
}

export type ArchitecturePanels = ArchitecturePanelHost & {
  /** Selects a map entity and opens its detail panel; focus later returns to the entity's map node. */
  selectCanvasEntity(entityId: string): void
  /** Opens What-if, closing the editor first when it is the open panel. */
  openScenario(opener: HTMLElement): void
  /** Opens What-if and scrolls its picker to `decisionId`. */
  exploreDecision(decisionId: string): void
  /** Closes the open panel and returns focus to its opener (backdrop click). */
  close(): void
}

export function useArchitecturePanelHost(): ArchitecturePanelHost {
  const [architecturePanel, setArchitecturePanel] = useState<ArchitecturePanel | null>(null)
  const architecturePanelRef = useRef<HTMLElement | null>(null)
  const panelOpenerRef = useRef<HTMLElement | null>(null)
  return { panel: architecturePanel, setPanel: setArchitecturePanel, panelRef: architecturePanelRef, openerRef: panelOpenerRef }
}

/** `closeDeltaEditor` must be stable; the Escape listener re-binds when it or the open panel changes. */
export function useArchitecturePanels(host: ArchitecturePanelHost, closeDeltaEditor: () => void, setSelectedEntity: (entityId: string) => void, jumpToScenarioDecision: (decisionId: string) => void): ArchitecturePanels {
  const { panel: architecturePanel, setPanel: setArchitecturePanel, panelRef: architecturePanelRef, openerRef: panelOpenerRef } = host

  const selectCanvasEntity = (entityId: string) => {
    panelOpenerRef.current = [...document.querySelectorAll<HTMLElement>('.react-flow__node')].find((node) => node.dataset.id === entityId) ?? null
    setSelectedEntity(entityId)
    setArchitecturePanel('detail')
  }
  useEffect(() => {
    if (!architecturePanel) return
    const frame = window.requestAnimationFrame(() => {
      const firstControl = architecturePanelRef.current?.querySelector<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')
      firstControl?.focus({ preventScroll: true })
    })
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (event.defaultPrevented) return
        if (architecturePanel === 'editor') closeDeltaEditor()
        else setArchitecturePanel(null)
        const opener = panelOpenerRef.current
        panelOpenerRef.current = null
        window.requestAnimationFrame(() => opener?.focus({ preventScroll: true }))
      }
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('keydown', closeOnEscape)
    }
  }, [architecturePanel, closeDeltaEditor, architecturePanelRef, panelOpenerRef, setArchitecturePanel])

  function exploreDecision(decisionId: string) {
    setArchitecturePanel('scenario')
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => jumpToScenarioDecision(decisionId)))
  }

  function closeArchitectureOverlay() {
    const opener = panelOpenerRef.current
    panelOpenerRef.current = null
    if (architecturePanel === 'editor') closeDeltaEditor()
    else setArchitecturePanel(null)
    window.requestAnimationFrame(() => opener?.focus({ preventScroll: true }))
  }

  return {
    ...host,
    selectCanvasEntity,
    openScenario(opener) {
      panelOpenerRef.current = opener
      if (architecturePanel === 'editor') closeDeltaEditor()
      setArchitecturePanel('scenario')
    },
    exploreDecision,
    close: closeArchitectureOverlay,
  }
}
