// Defaults for a new model-connection form draft.

export const OLLAMA_ENDPOINT = 'http://host.docker.internal:11434/v1'
const CONNECTION_CAPABILITIES = { structured_output: true, embeddings: false, streaming: true }

export function createConnectionDraft(provider = 'openai') {
  return { name: '', id: '', provider, endpoint: provider === 'ollama' ? OLLAMA_ENDPOINT : '', model: '', embedding_model: '', credential_ref: '', capabilities: CONNECTION_CAPABILITIES }
}

export function canConfigureEndpoint(provider: string): boolean {
  return provider === 'ollama' || provider === 'openai_compatible'
}

export function endpointPlaceholder(provider: string): string {
  return provider === 'ollama' ? OLLAMA_ENDPOINT : 'https://gateway.example.com/v1'
}
