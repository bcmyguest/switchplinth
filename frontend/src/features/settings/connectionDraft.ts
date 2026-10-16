// Defaults for a new model-connection form draft, and the draft's request-timeout field.
import type { ConnectionGeneration } from '../../types'

export const OLLAMA_ENDPOINT = 'http://host.docker.internal:11434/v1'
const CONNECTION_CAPABILITIES = { structured_output: true, embeddings: false, streaming: true }
// Upper bound from the bundled record schema (generation.request_timeout_seconds).
const MAX_REQUEST_TIMEOUT_SECONDS = 86400

/** `generation` holds the stored settings so a save keeps the keys this form does not edit. */
export function createConnectionDraft(provider = 'openai', generation: ConnectionGeneration = {}) {
  return { name: '', id: '', provider, endpoint: provider === 'ollama' ? OLLAMA_ENDPOINT : '', model: '', embedding_model: '', credential_ref: '', capabilities: CONNECTION_CAPABILITIES, generation, request_timeout_seconds: generation.request_timeout_seconds?.toString() ?? '' }
}

export function canConfigureEndpoint(provider: string): boolean {
  return provider === 'ollama' || provider === 'openai_compatible'
}

export function endpointPlaceholder(provider: string): string {
  return provider === 'ollama' ? OLLAMA_ENDPOINT : 'https://gateway.example.com/v1'
}

/** Returns a validation message for the timeout field, or '' when it is blank or valid. */
export function requestTimeoutError(text: string): string {
  if (!text.trim()) return ''
  const seconds = Number(text)
  return Number.isFinite(seconds) && seconds > 0 && seconds <= MAX_REQUEST_TIMEOUT_SECONDS ? '' : `Request timeout must be a number of seconds above 0 and at most ${MAX_REQUEST_TIMEOUT_SECONDS}.`
}

/**
 * Merges the timeout field into the stored generation settings.
 * The backend keeps stored generation when the key is omitted and clears it on {}, so a blank
 * timeout omits generation unless a stored timeout must be removed.
 */
export function connectionGeneration(stored: ConnectionGeneration, timeoutText: string): ConnectionGeneration | undefined {
  const { request_timeout_seconds: storedTimeout, ...rest } = stored
  const generation: ConnectionGeneration = timeoutText.trim() ? { ...rest, request_timeout_seconds: Number(timeoutText) } : rest
  return Object.keys(generation).length || storedTimeout !== undefined ? generation : undefined
}
