import { useCallback, useEffect, useRef, useState, type RefObject } from 'react'
import type { ReactFlowInstance, Viewport } from '@xyflow/react'
import { fitMapViewport } from './useArchitectureMap'

const FULLSCREEN_CLASS = 'map-fullscreen'
// Browser full-screen transitions resize the window late; re-apply the viewport after resizes settle.
const SETTLE_DELAY_MS = 140
const SETTLE_WINDOW_MS = 1200

type UseMapFullscreenOptions = {
  active: boolean
  overlayOpen: boolean
  flowInstanceRef: RefObject<ReactFlowInstance | null>
  fitViewOptions: { padding: number; minZoom: number }
}

// Full screen targets the document element so portaled dialogs, selects, and the fixed map overlays
// stay inside the full-screen tree. A CSS mode on <html> makes the map frame fill the viewport; it
// also serves as the fallback when the Fullscreen API is unavailable or refused. When Escape reaches
// the page, the first press closes an open overlay and the next leaves full screen. A browser that
// consumes Escape for its own full-screen exit (Firefox does) leaves full screen first and keeps the
// overlay open; that overlay keeps focus.
export function useMapFullscreen({ active, overlayOpen, flowInstanceRef, fitViewOptions }: UseMapFullscreenOptions) {
  const [fullscreen, setFullscreen] = useState(false)
  const toggleRef = useRef<HTMLButtonElement | null>(null)
  const activeRef = useRef(false)
  const savedViewport = useRef<Viewport | null>(null)
  const settleCleanup = useRef<(() => void) | null>(null)
  const fitOptionsRef = useRef(fitViewOptions)
  const overlayOpenRef = useRef(overlayOpen)
  useEffect(() => { fitOptionsRef.current = fitViewOptions }, [fitViewOptions])
  useEffect(() => { overlayOpenRef.current = overlayOpen }, [overlayOpen])

  const settle = useCallback((apply: () => void) => {
    settleCleanup.current?.()
    let timer = window.setTimeout(apply, SETTLE_DELAY_MS)
    const onResize = () => { window.clearTimeout(timer); timer = window.setTimeout(apply, SETTLE_DELAY_MS) }
    window.addEventListener('resize', onResize)
    const stop = window.setTimeout(() => window.removeEventListener('resize', onResize), SETTLE_WINDOW_MS)
    settleCleanup.current = () => { window.clearTimeout(timer); window.clearTimeout(stop); window.removeEventListener('resize', onResize) }
  }, [])

  const leave = useCallback(() => {
    if (!activeRef.current) return
    activeRef.current = false
    setFullscreen(false)
    const viewport = savedViewport.current
    savedViewport.current = null
    settle(() => {
      const flow = flowInstanceRef.current
      if (viewport) void flow?.setViewport(viewport, { duration: 0 })
      else void fitMapViewport(flow, fitOptionsRef.current)
    })
    // An overlay that survives the exit keeps focus; its own close handler returns focus to its opener.
    requestAnimationFrame(() => { if (!overlayOpenRef.current) toggleRef.current?.focus() })
  }, [flowInstanceRef, settle])

  const exit = useCallback(() => {
    leave()
    if (document.fullscreenElement) void document.exitFullscreen().catch(() => undefined)
  }, [leave])

  const enter = useCallback(() => {
    if (activeRef.current) return
    activeRef.current = true
    savedViewport.current = flowInstanceRef.current?.getViewport() ?? null
    setFullscreen(true)
    settle(() => { void fitMapViewport(flowInstanceRef.current, fitOptionsRef.current) })
    const root = document.documentElement
    if (!document.fullscreenElement && typeof root.requestFullscreen === 'function') void root.requestFullscreen().catch(() => undefined)
  }, [flowInstanceRef, settle])

  const toggle = useCallback(() => { if (fullscreen) exit(); else enter() }, [fullscreen, enter, exit])

  useEffect(() => {
    const root = document.documentElement
    root.classList.toggle(FULLSCREEN_CLASS, fullscreen)
    return () => root.classList.remove(FULLSCREEN_CLASS)
  }, [fullscreen])

  useEffect(() => {
    // Mirror a browser-initiated exit (Escape, F11, system UI) into the CSS mode.
    const syncFromDocument = () => { if (!document.fullscreenElement) leave() }
    document.addEventListener('fullscreenchange', syncFromDocument)
    return () => document.removeEventListener('fullscreenchange', syncFromDocument)
  }, [leave])

  useEffect(() => {
    if (!fullscreen) return
    // Escape that reaches the page: the first press closes an open overlay, the next one leaves full screen.
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape' && !overlayOpen && !event.defaultPrevented) exit() }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [fullscreen, overlayOpen, exit])

  useEffect(() => { if (!active && fullscreen) exit() }, [active, fullscreen, exit])

  useEffect(() => () => settleCleanup.current?.(), [])

  return { fullscreen, toggle, exit, toggleRef }
}
