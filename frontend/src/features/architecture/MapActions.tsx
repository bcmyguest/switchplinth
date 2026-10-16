// Map editing controls below the system map: add a component, remove the selected component, and open or close the delta editor.
import { Code2, Plus, X } from 'lucide-react'
import type { GraphData } from '../../types'
import type { DeltaEditor } from '../graph-editor/useDeltaEditor'

type MapActionsProps = {
  editor: DeltaEditor
  graph: GraphData
  live: boolean
  selectedEntity: string
}

export function MapActions({ editor, graph, live, selectedEntity }: MapActionsProps) {
  return <div className="map-actions" aria-label="Map editing controls"><button className="button tiny-button" onClick={(event) => { editor.open(event.currentTarget); editor.form.setKind('add_entity'); editor.form.setShow(true) }} disabled={!live || graph.decisions.length === 0}><Plus size={14} /> Add component</button><button className="button tiny-button" onClick={() => editor.removeEntity(selectedEntity)} disabled={!live || !graph.entities.some((entity) => entity.id === selectedEntity)}><X size={14} /> Remove selected</button><button className="button tiny-button" onClick={(event) => editor.isOpen ? editor.close() : editor.open(event.currentTarget)} disabled={!live || graph.decisions.length === 0}><Code2 size={14} /> {editor.isOpen ? 'Close editor' : 'Edit delta'}</button></div>
}
