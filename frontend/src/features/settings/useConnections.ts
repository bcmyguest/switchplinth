// Model connections: the saved list, the selected connection, provider diagnostics, and the settings dialog's form state.
// The list loads once on mount; a repository switch replaces it through `reset()` and `load()`.
import { useEffect, useState, type Dispatch, type FormEvent, type SetStateAction } from 'react'
import { getConnections, saveConnection, testConnection } from '../../api'
import { demoConnection } from '../../demo'
import type { Workspace } from '../../app/useWorkspace'
import type { Connection } from '../../types'
import { canConfigureEndpoint, connectionGeneration, createConnectionDraft, requestTimeoutError } from './connectionDraft'

type ConnectionDraft = ReturnType<typeof createConnectionDraft>

type ConnectionSettingsState = {
  open: boolean
  setOpen: (open: boolean) => void
  providerBusy: boolean
  formOpen: boolean
  setFormOpen: (open: boolean) => void
  draft: ConnectionDraft
  setDraft: Dispatch<SetStateAction<ConnectionDraft>>
  error: string
  /** Runs the active connection's capability checks and stores the diagnostics on it. */
  check(): Promise<void>
  /** Saves the form draft, reloads the list, and selects the saved connection. */
  save(event: FormEvent<HTMLFormElement>): Promise<void>
  /** Opens the form on the active connection, or on a blank draft for the demo connection. */
  edit(): void
}

export type Connections = {
  list: Connection[]
  selectedId: string
  /** The selected connection, else the first one; the demo connection while the backend is offline. */
  active: Connection | undefined
  select(id: string): void
  openSettings(): void
  /** Replaces the list after a repository switch and selects its first connection. */
  load(list: Connection[]): void
  /** Clears the list and the selection when another repository opens. */
  reset(): void
  dialog: ConnectionSettingsState
}

export function useConnections(workspace: Pick<Workspace, 'live' | 'generation' | 'setLive'>): Connections {
  const { live, generation, setLive } = workspace
  const [connections, setConnections] = useState<Connection[]>([])
  const [selectedConnectionId, setSelectedConnectionId] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [providerBusy, setProviderBusy] = useState(false)
  const [connectionForm, setConnectionForm] = useState(false)
  const [connectionDraft, setConnectionDraft] = useState(createConnectionDraft)
  const [connectionError, setConnectionError] = useState('')

  useEffect(() => {
    const loadGeneration = generation.current
    void getConnections().then((items) => { if (loadGeneration === generation.current) { setConnections(items); setSelectedConnectionId(items[0]?.id ?? '') } }).catch(() => { if (loadGeneration === generation.current) setConnections([]) })
  }, [generation])

  const activeConnection = connections.find((connection) => connection.id === selectedConnectionId) ?? connections[0] ?? (live ? undefined : demoConnection)

  async function checkProvider() {
    if (!live || !activeConnection) return
    setProviderBusy(true)
    try {
      const result = await testConnection(activeConnection.id)
      const hasError = Object.values(result.capabilities).some((item) => item.status === 'error')
      setConnections((current) => current.map((connection) => connection.id === activeConnection.id ? { ...connection, status: hasError ? 'error' : 'checked', latency_ms: result.latency_ms, diagnostics: result.capabilities } : connection))
    } catch (error) {
      setConnections((current) => current.map((connection) => connection.id === activeConnection.id ? { ...connection, status: 'error', diagnostics: { ...connection.diagnostics, request: { status: 'error', raw_error: error instanceof Error ? error.message : 'Connection check failed', normalized_error: 'The backend could not complete provider diagnostics.', detail: 'Check backend availability, connection settings, and service logs.' } } } : connection))
    } finally {
      setProviderBusy(false)
    }
  }

  async function createConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setConnectionError('')
    const timeoutError = requestTimeoutError(connectionDraft.request_timeout_seconds)
    if (timeoutError) { setConnectionError(timeoutError); return }
    try {
      const { generation: storedGeneration, request_timeout_seconds: timeoutText, ...draft } = connectionDraft
      const id = draft.id || draft.name.toLowerCase().replace(/[^a-z0-9]+/g, '-')
      const saved = await saveConnection({ ...draft, id, generation: connectionGeneration(storedGeneration, timeoutText), endpoint: canConfigureEndpoint(draft.provider) ? draft.endpoint.trim() || undefined : undefined, embedding_model: draft.embedding_model.trim() || undefined, credential_ref: draft.credential_ref || undefined })
      const refreshed = await getConnections()
      setConnections(refreshed)
      setSelectedConnectionId(id)
      setConnectionForm(false)
      setConnectionDraft(createConnectionDraft(connectionDraft.provider))
      setLive(true)
      if (saved) setConnectionError('')
    } catch (error) { setConnectionError(error instanceof Error ? error.message : 'Could not save this connection.') }
  }

  function editConnection() {
    if (!activeConnection || activeConnection.id === demoConnection.id) {
      setConnectionDraft(createConnectionDraft())
    } else {
      setConnectionDraft({ ...createConnectionDraft(activeConnection.provider, activeConnection.generation), name: activeConnection.name, id: activeConnection.id, endpoint: activeConnection.endpoint ?? '', model: activeConnection.model ?? '', embedding_model: activeConnection.embedding_model ?? '', credential_ref: activeConnection.credential_ref ?? '' })
    }
    setConnectionForm(true)
    setConnectionError('')
  }

  return {
    list: connections,
    selectedId: selectedConnectionId,
    active: activeConnection,
    select: setSelectedConnectionId,
    openSettings: () => setShowSettings(true),
    load(list) {
      setConnections(list)
      setSelectedConnectionId(list[0]?.id ?? '')
    },
    reset() {
      setConnections([])
      setSelectedConnectionId('')
    },
    dialog: {
      open: showSettings,
      setOpen: setShowSettings,
      providerBusy,
      formOpen: connectionForm,
      setFormOpen: setConnectionForm,
      draft: connectionDraft,
      setDraft: setConnectionDraft,
      error: connectionError,
      check: checkProvider,
      save: createConnection,
      edit: editConnection,
    },
  }
}
