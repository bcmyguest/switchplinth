// "Changes vs previous choice": requests the diff between the previously resolved selection and the newly resolved one,
// and drops any response that a newer switch, a reset, or a repository switch has made stale.
import { useRef, useState } from 'react'
import { diffScenarios } from '../../api'
import { presentScenarioDiff, type DiffNaming, type ScenarioDiffView } from './scenarioDiff'

type Selections = Record<string, string>

export type PreviousChoiceDiffState =
  | { status: 'idle' }
  /** A switch is resolving, or its diff request is in flight. */
  | { status: 'loading' }
  | { status: 'ready'; view: ScenarioDiffView }
  | { status: 'error'; message: string }

export type PreviousChoiceDiff = {
  state: PreviousChoiceDiffState
  /** Hides the current diff because a new switch started; a later `compare` or `clear` settles it. */
  begin(): void
  /** Compares `before` with `after`; `naming` names the IDs once the response arrives. */
  compare(before: Selections, after: Selections, naming: DiffNaming): void
  retry(): void
  /** Drops any in-flight request and shows nothing. */
  clear(): void
}

export function usePreviousChoiceDiff(repositoryGeneration: { readonly current: number }): PreviousChoiceDiff {
  const [state, setState] = useState<PreviousChoiceDiffState>({ status: 'idle' })
  const sequence = useRef(0)
  const lastRequest = useRef<Parameters<PreviousChoiceDiff['compare']> | null>(null)

  async function compare(before: Selections, after: Selections, naming: DiffNaming) {
    const requestSequence = ++sequence.current
    const generation = repositoryGeneration.current
    lastRequest.current = [before, after, naming]
    setState({ status: 'loading' })
    try {
      const diff = await diffScenarios(before, after)
      if (requestSequence !== sequence.current || generation !== repositoryGeneration.current) return
      setState({ status: 'ready', view: presentScenarioDiff(diff, naming) })
    } catch (error) {
      if (requestSequence !== sequence.current || generation !== repositoryGeneration.current) return
      setState({ status: 'error', message: error instanceof Error ? error.message : 'Could not compare with the previous choice.' })
    }
  }

  return {
    state,
    begin() {
      sequence.current += 1
      setState({ status: 'loading' })
    },
    compare(before, after, naming) { void compare(before, after, naming) },
    retry() { if (lastRequest.current) void compare(...lastRequest.current) },
    clear() {
      sequence.current += 1
      lastRequest.current = null
      setState({ status: 'idle' })
    },
  }
}
