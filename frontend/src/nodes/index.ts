import type { NodeTypes } from '@xyflow/react'
import { LlmNode } from './LlmNode'
import { ToolNode } from './ToolNode'
import { ToolkitNode } from './ToolkitNode'
import { MemoryNode } from './MemoryNode'
import { CacheNode } from './CacheNode'
import { DocLoaderNode } from './DocLoaderNode'
import { TextSplitterNode } from './TextSplitterNode'
import { EmbeddingNode } from './EmbeddingNode'
import { VectorStoreNode } from './VectorStoreNode'
import { RetrieverNode } from './RetrieverNode'
import { MasterAgentNode } from './MasterAgentNode'
import { ChildAgentNode } from './ChildAgentNode'
import { ConnectionNode } from './ConnectionNode'
import { KnowledgeBaseNode } from './KnowledgeBaseNode'
import { StartNode } from './StartNode'
import { StopNode } from './StopNode'
import { GatewayNode } from './GatewayNode'
import { SkillNode } from './SkillNode'
import { RerankerNode } from './RerankerNode'
import { HumanGateNode } from './HumanGateNode'
import { CheckpointerNode } from './CheckpointerNode'
import { WorkflowStepNode } from './WorkflowStepNode'
import { OutputParserNode } from './OutputParserNode'
import { MiddlewareNode } from './MiddlewareNode'
import { SyntheticDataNode } from './SyntheticDataNode'

export const nodeTypes: NodeTypes = {
  llm: LlmNode,
  tool: ToolNode,
  toolkit: ToolkitNode,
  memory: MemoryNode,
  cache: CacheNode,
  doc_loader: DocLoaderNode,
  text_splitter: TextSplitterNode,
  embedding: EmbeddingNode,
  vector_store: VectorStoreNode,
  retriever: RetrieverNode,
  reranker: RerankerNode,
  master_agent: MasterAgentNode,
  child_agent: ChildAgentNode,
  connection: ConnectionNode,
  knowledge_base: KnowledgeBaseNode,
  start: StartNode,
  stop: StopNode,
  gateway: GatewayNode,
  skill: SkillNode,
  human_gate: HumanGateNode,
  checkpointer: CheckpointerNode,
  wf_step: WorkflowStepNode,
  output_parser: OutputParserNode,
  middleware: MiddlewareNode,
  synthetic_data: SyntheticDataNode,
}

export { LlmNode, ToolNode, ToolkitNode, MemoryNode, CacheNode, DocLoaderNode, TextSplitterNode, EmbeddingNode, VectorStoreNode, RetrieverNode, RerankerNode, MasterAgentNode, ChildAgentNode, ConnectionNode, KnowledgeBaseNode, StartNode, StopNode, GatewayNode, SkillNode, HumanGateNode, CheckpointerNode, WorkflowStepNode, OutputParserNode, MiddlewareNode, SyntheticDataNode }
