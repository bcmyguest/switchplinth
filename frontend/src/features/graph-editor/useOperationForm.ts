// Field state for the typed-operation form in the option delta editor. It holds the form values only; the delta editor turns
// them into operations.
import { useState } from 'react'

type OperationKind = 'add_entity' | 'remove_entity' | 'add_relationship' | 'remove_relationship'

export type OperationForm = {
  show: boolean
  setShow: (update: boolean | ((show: boolean) => boolean)) => void
  kind: OperationKind
  setKind: (kind: OperationKind) => void
  entityId: string
  setEntityId: (entityId: string) => void
  entityName: string
  setEntityName: (entityName: string) => void
  entityKind: string
  setEntityKind: (entityKind: string) => void
  from: string
  setFrom: (from: string) => void
  to: string
  setTo: (to: string) => void
  /** The relationship kind used by the form and by canvas connections. */
  relationKind: string
  setRelationKind: (relationKind: string) => void
  relationId: string
  setRelationId: (relationId: string) => void
}

export function useOperationForm(): OperationForm {
  const [showOperationForm, setShowOperationForm] = useState(false)
  const [operationKind, setOperationKind] = useState<OperationKind>('add_relationship')
  const [operationEntityId, setOperationEntityId] = useState('')
  const [operationEntityName, setOperationEntityName] = useState('')
  const [operationEntityKind, setOperationEntityKind] = useState('service')
  const [operationFrom, setOperationFrom] = useState('')
  const [operationTo, setOperationTo] = useState('')
  const [operationRelationKind, setOperationRelationKind] = useState('depends_on')
  const [operationRelationId, setOperationRelationId] = useState('')
  return {
    show: showOperationForm,
    setShow: setShowOperationForm,
    kind: operationKind,
    setKind: setOperationKind,
    entityId: operationEntityId,
    setEntityId: setOperationEntityId,
    entityName: operationEntityName,
    setEntityName: setOperationEntityName,
    entityKind: operationEntityKind,
    setEntityKind: setOperationEntityKind,
    from: operationFrom,
    setFrom: setOperationFrom,
    to: operationTo,
    setTo: setOperationTo,
    relationKind: operationRelationKind,
    setRelationKind: setOperationRelationKind,
    relationId: operationRelationId,
    setRelationId: setOperationRelationId,
  }
}
