// React Flow node and edge type registries for the architecture map. Kept in a .ts file so component modules export only components.
import { ArchitectureNode } from './ArchitectureNode'
import { GroupNode } from './GroupNode'
import { OrthogonalEdge } from './OrthogonalEdge'
import { ReadableEdge } from './ReadableEdge'

export const NODE_TYPES = { architecture: ArchitectureNode, mapGroup: GroupNode }
export const EDGE_TYPES = { readable: ReadableEdge, orthogonal: OrthogonalEdge }
