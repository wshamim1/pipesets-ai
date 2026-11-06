import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm } from './_helpers'

export const BLUEPRINT: Blueprint = {
  id: 'tpl-handbook-chat',
  name: 'Handbook Q&A with Memory',
  description: 'Indexes a Markdown handbook and answers follow-up questions with hybrid keyword + vector search, reranking, and chat memory.',
  badge: 'RAG Pipeline',
  icon: '📘',
  order: 100,
  build() {
    const embedding = { provider: 'local', model: 'sentence-transformers/all-MiniLM-L6-v2' } as const
    const nodes: FlowNode[] = [
      { id: 'start-1', type: 'start', position: { x: 50, y: 280 }, data: { label: 'Start' } },
      { id: 'loader-1', type: 'doc_loader', position: { x: 220, y: 120 }, data: {
        label: 'Handbook Loader', loader_type: 'markdown', source: '/path/to/handbook.md', chunk_strategy: 'paragraph',
      }},
      { id: 'splitter-1', type: 'text_splitter', position: { x: 430, y: 120 }, data: {
        label: 'Markdown Splitter', splitter_type: 'recursive_character', chunk_size: 800, chunk_overlap: 100,
      }},
      { id: 'embed-1', type: 'embedding', position: { x: 640, y: 120 }, data: {
        label: 'Local Embedding', ...embedding, api_key: '',
      }},
      { id: 'store-1', type: 'vector_store', position: { x: 850, y: 120 }, data: {
        label: 'Local Vector Store', store_type: 'local', collection_name: 'handbook', connection_string: '', top_k: 8,
      }},
      { id: 'retriever-1', type: 'retriever', position: { x: 640, y: 320 }, data: {
        label: 'Hybrid Retriever', search_type: 'bm25_hybrid', collection_name: 'handbook', top_k: 6,
        score_threshold: 0, rerank: true,
        embedding_provider: embedding.provider, embedding_model: embedding.model, embedding_api_key: '',
      }},
      { id: 'llm-1', type: 'llm', position: { x: 850, y: 320 }, data: llm(
        'Handbook LLM',
        'Answer questions using only the retrieved handbook sections. Name the section each claim comes from, '
        + 'and say so when the handbook does not cover the question.\n\nContext:\n{{context}}',
        0.2,
      )},
      { id: 'memory-1', type: 'memory', position: { x: 850, y: 500 }, data: {
        label: 'Chat Memory', strategy: 'sliding_window', token_budget: 3000, session_id: 'handbook-chat', session_ttl_hours: 12,
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
      edge('e-llm-memory', 'llm-1', 'memory-1'),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
