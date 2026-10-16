// Map editing controls below the system map: add a component, remove the selected component, and open or close the delta editor.
import { Code2, Plus, X } from 'lucide-react'
import { Button } from '../../components/ui/button'
import type { GraphData } from '../../types'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'

type MapActionsProps = {
  editor: DeltaEditor
  graph: GraphData
  live: boolean
  selectedEntity: string
}

/** Map editing actions share the row and grow to fill it on mobile. */
const MAP_ACTION = 'text-(length:--type-control) max-sm:flex-auto max-sm:justify-center'

export function MapActions({ editor, graph, live, selectedEntity }: MapActionsProps) {
  return <div className="map-actions" aria-label="Map editing controls"><Button variant="subtle" size="tiny" className={MAP_ACTION} onClick={(event) => { editor.open(event.currentTarget); editor.form.setKind('add_entity'); editor.form.setShow(true) }} disabled={!live || graph.decisions.length === 0}><Plus size={14} /> Add component</Button><Button variant="subtle" size="tiny" className={MAP_ACTION} onClick={() => editor.removeEntity(selectedEntity)} disabled={!live || !graph.entities.some((entity) => entity.id === selectedEntity)}><X size={14} /> Remove selected</Button><Button variant="subtle" size="tiny" className={MAP_ACTION} onClick={(event) => editor.isOpen ? editor.close() : editor.open(event.currentTarget)} disabled={!live || graph.decisions.length === 0}><Code2 size={14} /> {editor.isOpen ? 'Close editor' : 'Edit delta'}</Button></div>
}
