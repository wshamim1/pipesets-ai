import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-rag',
  name: 'RAG Document Assistant',
  description: 'Pre-configured PDF Loader with Recursive Splitter, Local Embeddings, and Chroma Vector Store.',
  badge: 'RAG Pipeline',
  icon: '📚',
  order: 10,
  build() {
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 50, y: 280 }, data: { label: 'Start' } },
      { id: 'loader-1', type: 'doc_loader', position: { x: 220, y: 120 }, data: {
        label: 'PDF Loader', loader_type: 'pdf', source: '/path/to/docs.pdf', chunk_strategy: 'fixed',
      }},
      { id: 'splitter-1', type: 'text_splitter', position: { x: 430, y: 120 }, data: {
        label: 'Recursive Splitter', splitter_type: 'recursive_character', chunk_size: 512, chunk_overlap: 50,
      }},
      { id: 'embed-1', type: 'embedding', position: { x: 640, y: 120 }, data: {
        label: 'Local Embedding', provider: 'local', model: 'sentence-transformers/all-MiniLM-L6-v2', api_key: '',
      }},
      { id: 'store-1', type: 'vector_store', position: { x: 850, y: 120 }, data: {
        label: 'Local Vector Store', store_type: 'local', collection_name: 'rag_docs', connection_string: '', top_k: 5,
      }},
      { id: 'retriever-1', type: 'retriever', position: { x: 640, y: 320 }, data: {
        label: 'Similarity Retriever', search_type: 'similarity', collection_name: 'rag_docs', top_k: 4,
        score_threshold: 0, rerank: false,
        embedding_provider: 'local', embedding_model: 'sentence-transformers/all-MiniLM-L6-v2', embedding_api_key: '',
      }},
      { id: 'llm-1', type: 'llm', position: { x: 850, y: 320 }, data: {
        label: 'RAG Answer LLM', provider: 'openai', model: 'gpt-4o',
        temperature: 0.3, max_tokens: 1024, top_p: 1.0, api_key: '',
        system_prompt: 'Answer using retrieved context. If context is missing, say so clearly.\n\nContext:\n{{context}}',
        base_url: '',
      }},
      { id: 'stop-1', type: 'stop', position: { x: 1060, y: 320 }, data: { label: 'Stop' } },
    ]
    const edges: FlowEdge[] = [
      edge('e-start-loader', 'start-1', 'loader-1'),
      edge('e-loader-splitter', 'loader-1', 'splitter-1'),
      edge('e-splitter-embed', 'splitter-1', 'embed-1'),
      edge('e-embed-store', 'embed-1', 'store-1'),
      edge('e-store-retriever', 'store-1', 'retriever-1'),
      edge('e-retriever-llm', 'retriever-1', 'llm-1'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
