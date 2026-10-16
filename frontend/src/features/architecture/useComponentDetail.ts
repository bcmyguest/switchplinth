// Component detail: the selected entity, its stale-guarded detail fetch, and the derived panel values.
import { useEffect, useRef, useState, type Dispatch, type SetStateAction } from 'react'
import { getEntityDetail } from '../../api'
import type { Workspace } from '../../app/useWorkspace'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'
import { deriveComponentDetail, type ComponentDetail, type EntityDetail } from './componentDetail'

export type ComponentDetailController = ComponentDetail & {
  /** The requested entity ID; `selected` falls back to the first visible entity when it is absent. */
  selectedId: string
  select: Dispatch<SetStateAction<string>>
  /** Clears this module's share of the repository-switch reset: the selected entity and the fetched detail. */
  reset(): void
}

export function useComponentDetail(workspace: Pick<Workspace, 'graph' | 'live'>, displayedSelection: Record<string, string>, deltaPreview: DeltaEditor['preview']): ComponentDetailController {
  const { graph, live } = workspace
  const [selectedEntity, setSelectedEntity] = useState('technology-kafka')
  const [entityDetail, setEntityDetail] = useState<EntityDetail | null>(null)
  const entityDetailRequestSequence = useRef(0)
  const visibleGraph = deltaPreview?.graph ?? graph
  const detail = deriveComponentDetail({ graph, visibleGraph, selectedId: selectedEntity, entityDetail, displayed: displayedSelection, preview: deltaPreview })
  const visibleSelectedEntityId = detail.visibleSelectedEntityId

  useEffect(() => {
    const requestSequence = ++entityDetailRequestSequence.current
    if (!live || !visibleSelectedEntityId) { setEntityDetail(null); return }
    setEntityDetail(null)
    const detailSelections = deltaPreview ? { ...displayedSelection, [deltaPreview.decisionId]: deltaPreview.optionId } : displayedSelection
    void getEntityDetail(visibleSelectedEntityId, detailSelections).then((detail) => {
      if (entityDetailRequestSequence.current === requestSequence) setEntityDetail(detail)
    }).catch(() => {
      if (entityDetailRequestSequence.current === requestSequence) setEntityDetail(null)
    })
  }, [live, visibleSelectedEntityId, displayedSelection, deltaPreview, graph])

  return {
    ...detail,
    selectedId: selectedEntity,
    select: setSelectedEntity,
    reset() {
      setSelectedEntity('')
      setEntityDetail(null)
    },
  }
}
