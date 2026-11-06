import type { EmbeddingNodeData, FlowNode } from '../../types'
import { ApiKeyField } from './ApiKeyField'

interface Props {
  activeNode: FlowNode
  onUpdate: (nodeId: string, fields: Record<string, any>) => void
  onDelete: (nodeId: string) => void
  onSave: () => void
  readOnly?: boolean
}

const PROVIDER_OPTIONS: { value: EmbeddingNodeData['provider']; label: string }[] = [
  { value: 'openai',       label: 'OpenAI — text-embedding-3-small / large' },
  { value: 'local',        label: 'Local — sentence-transformers (HuggingFace)' },
  { value: 'cohere',       label: 'Cohere — embed-english-v3.0 / multilingual' },
  { value: 'google',       label: 'Google — text-embedding-004 (Gemini)' },
  { value: 'azure_openai', label: 'Azure OpenAI — deployed embedding model' },
  { value: 'mistral',      label: 'Mistral — mistral-embed' },
  { value: 'ollama',       label: 'Ollama — local models (nomic-embed-text, mxbai)' },
  { value: 'llamacpp',     label: 'llama.cpp — local llama-server (GGUF embedding models)' },
  { value: 'bedrock',      label: 'AWS Bedrock — Titan / Cohere on Bedrock' },
  { value: 'voyage',       label: 'Voyage AI — voyage-3, voyage-code-3' },
  { value: 'nomic',        label: 'Nomic — nomic-embed-text-v1.5' },
  { value: 'anthropic',    label: 'Anthropic — (via Voyage AI integration)' },
]

const MODELS_BY_PROVIDER: Record<string, string[]> = {
  openai: [
    'text-embedding-3-small',
    'text-embedding-3-large',
    'text-embedding-ada-002',
  ],
  local: [
    'sentence-transformers/all-MiniLM-L6-v2',
    'sentence-transformers/all-mpnet-base-v2',
    'BAAI/bge-small-en-v1.5',
    'BAAI/bge-large-en-v1.5',
    'BAAI/bge-m3',
    'intfloat/e5-large-v2',
  ],
  cohere: [
    'embed-english-v3.0',
    'embed-multilingual-v3.0',
    'embed-english-light-v3.0',
    'embed-multilingual-light-v3.0',
  ],
  google: [
    'text-embedding-004',
    'text-multilingual-embedding-002',
    'embedding-001',
  ],
  azure_openai: [
    'text-embedding-3-small',
    'text-embedding-3-large',
    'text-embedding-ada-002',
  ],
  mistral: [
    'mistral-embed',
  ],
  ollama: [
    'nomic-embed-text',
    'mxbai-embed-large',
    'all-minilm',
    'bge-m3',
  ],
  llamacpp: [
    'default',
  ],
  bedrock: [
    'amazon.titan-embed-text-v2:0',
    'amazon.titan-embed-text-v1',
    'cohere.embed-english-v3',
    'cohere.embed-multilingual-v3',
  ],
  voyage: [
    'voyage-3',
    'voyage-3-lite',
    'voyage-code-3',
    'voyage-finance-2',
    'voyage-multilingual-2',
  ],
  nomic: [
    'nomic-embed-text-v1.5',
    'nomic-embed-text-v1',
  ],
  anthropic: [
    'voyage-3',
    'voyage-3-lite',
  ],
}

const API_KEY_LABEL: Record<string, string> = {
  openai:       'OpenAI API Key',
  local:        'HuggingFace Token (optional)',
  cohere:       'Cohere API Key',
  google:       'Google API Key',
  azure_openai: 'Azure OpenAI API Key',
  mistral:      'Mistral API Key',
  ollama:       'Ollama Base URL',
  llamacpp:     'llama-server Base URL',
  bedrock:      'AWS Access Key ID',
  voyage:       'Voyage AI API Key',
  nomic:        'Nomic API Key',
  anthropic:    'Voyage AI API Key (for Anthropic)',
}

const API_KEY_PLACEHOLDER: Record<string, string> = {
  openai:       'sk-...',
  local:        'hf_... (optional for public models)',
  cohere:       'co-...',
  google:       'AIza...',
  azure_openai: 'your-azure-api-key',
  mistral:      'your-mistral-key',
  ollama:       'http://localhost:11434',
  llamacpp:     'http://localhost:8080',
  bedrock:      'AKIA...',
  voyage:       'pa-...',
  nomic:        'nk-...',
  anthropic:    'pa-... (Voyage key)',
}

const API_KEY_HINT: Record<string, string> = {
  openai:       'Required for OpenAI embedding API calls.',
  local:        'Leave blank for public HuggingFace models.',
  cohere:       'Required for Cohere Embed API calls.',
  google:       'Enable the Generative Language API in your GCP project.',
  azure_openai: 'Also set AZURE_API_BASE env var to your endpoint URL.',
  mistral:      'mistral-embed is the only Mistral embedding model.',
  ollama:       'Point to your Ollama server. Run `ollama pull nomic-embed-text` first.',
  llamacpp:     'Point to your llama-server, started with `--embeddings` and an embedding GGUF model.',
  bedrock:      'Also set AWS_SECRET_ACCESS_KEY and AWS_DEFAULT_REGION env vars.',
  voyage:       'voyage-3 is the flagship general model; voyage-code-3 for code.',
  nomic:        'nomic-embed-text-v1.5 supports Matryoshka (variable dimensions).',
  anthropic:    'Anthropic uses Voyage AI for embeddings under the hood.',
}

export function EmbeddingConfigPanel({ activeNode, onUpdate, onDelete, onSave, readOnly }: Props) {
  const data = activeNode.data as EmbeddingNodeData

  const modelOptions = MODELS_BY_PROVIDER[data.provider] ?? MODELS_BY_PROVIDER['openai']

  return (
    <div className="bottom-config-grid">
      <div className="config-card">
        <h4 className="card-heading">1. Identity &amp; Provider</h4>
        <div className="form-group">
          <label className="field-label">Node Label</label>
          <input type="text" className="field-input" value={data.label} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { label: e.target.value })} />
        </div>
        <div className="form-group">
          <label className="field-label">Provider</label>
          <select className="field-select" value={data.provider} disabled={readOnly}
            onChange={(e) => {
              const prov = e.target.value as EmbeddingNodeData['provider']
              const models = MODELS_BY_PROVIDER[prov] ?? []
              onUpdate(activeNode.id, { provider: prov, model: models[0] ?? '' })
            }}>
            {PROVIDER_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">2. Model</h4>
        <div className="form-group">
          <label className="field-label">Embedding Model</label>
          <select className="field-select" value={data.model} disabled={readOnly}
            onChange={(e) => onUpdate(activeNode.id, { model: e.target.value })}>
            {modelOptions.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
          <span className="field-hint">
            {data.provider === 'openai'
              ? 'text-embedding-3-small is the best price/quality ratio. 3-large gives highest accuracy.'
              : data.provider === 'local'
              ? 'Runs locally via sentence-transformers. No API key required.'
              : data.provider === 'cohere'
              ? 'embed-english-v3.0 is best for English; multilingual supports 100+ languages.'
              : data.provider === 'google'
              ? 'text-embedding-004 is the latest and most capable Google embedding model.'
              : data.provider === 'bedrock'
              ? 'Titan v2 supports variable dimensions. Cohere models require Bedrock access.'
              : data.provider === 'voyage'
              ? 'voyage-3 is the flagship. voyage-code-3 excels at code retrieval tasks.'
              : 'Select the model appropriate for your use case.'}
          </span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">3. API Key / Credentials</h4>
        <div className="form-group">
          <label className="field-label">{API_KEY_LABEL[data.provider] ?? 'API Key'}</label>
          {data.provider === 'ollama' || data.provider === 'llamacpp' ? (
            // Local servers: this field carries the base URL, not a key
            <input type="password" className="field-input code-font"
              placeholder={API_KEY_PLACEHOLDER[data.provider] ?? ''}
              value={data.api_key}
              disabled={readOnly}
              onChange={(e) => onUpdate(activeNode.id, { api_key: e.target.value })} />
          ) : (
            <ApiKeyField
              provider={({ google: 'gemini', azure_openai: 'openai', local: 'huggingface' } as Record<string, string>)[data.provider] ?? data.provider}
              value={data.api_key} readOnly={readOnly} placeholder={API_KEY_PLACEHOLDER[data.provider] ?? ''}
              onChange={(v) => onUpdate(activeNode.id, { api_key: v })} />
          )}
          <span className="field-hint">{API_KEY_HINT[data.provider] ?? ''}</span>
        </div>
      </div>

      <div className="config-card">
        <h4 className="card-heading">4. Node Actions</h4>
        <div className="tool-status-box emb-status-box">
          <span className="status-dot emb-dot" />
          <span>Converts text chunks into dense vectors</span>
        </div>
        {!readOnly && (
          <div className="card-actions-row">
            <button type="button" className="save-btn" onClick={onSave}>Save to App</button>
            <button type="button" className="delete-btn" onClick={() => onDelete(activeNode.id)}>Delete Node</button>
          </div>
        )}
      </div>
    </div>
  )
}
