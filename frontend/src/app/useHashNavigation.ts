// Hash navigation: the current page, back/forward and hash restoration, and scroll reset plus heading focus on page change.
import { useEffect, useRef, useState } from 'react'
import { PAGE_HASHES, pageFromLocation, type Page } from './navigation'

/**
 * `navigateTo` pushes one history entry per page change and ignores the current page. While mounted, browser scroll
 * restoration is manual; after each page change the window scrolls to the top and `headingRef` receives focus.
 */
export function useHashNavigation() {
  const [page, setPage] = useState<Page>(pageFromLocation)
  const headingRef = useRef<HTMLDivElement | null>(null)
  const previousPageRef = useRef(page)

  function navigateTo(next: Page) {
    if (next === page) return
    window.history.pushState(null, '', PAGE_HASHES[next])
    setPage(next)
  }

  useEffect(() => {
    const previousScrollRestoration = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    const restorePage = () => setPage(pageFromLocation())
    window.addEventListener('popstate', restorePage)
    window.addEventListener('hashchange', restorePage)
    return () => {
      window.removeEventListener('popstate', restorePage)
      window.removeEventListener('hashchange', restorePage)
      window.history.scrollRestoration = previousScrollRestoration
    }
  }, [])

  useEffect(() => {
    if (previousPageRef.current === page) return
    previousPageRef.current = page
    window.scrollTo(0, 0)
    headingRef.current?.focus({ preventScroll: true })
  }, [page])

  return { page, navigateTo, headingRef }
}
