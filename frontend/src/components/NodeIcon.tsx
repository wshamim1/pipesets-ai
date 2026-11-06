import {
  Binary, Bot, BotMessageSquare, HardDriveDownload, Boxes, Braces, Brain, CircleCheck, CircleDollarSign, Database, Eye, FileText,
  Gauge, GitBranch, Hand, Layers, Library, Link, List, ListChecks, ListOrdered, Megaphone,
  MessageCircleQuestion, Network, PenLine, Play, Plug, Puzzle, Route, Scissors, Search, ShieldAlert,
  ShieldCheck, ShieldX, Sparkles, Square, UserCheck, Wrench, Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * One line-icon set for the canvas and the sidebar, keyed by node type
 * (plus sidebar-only kinds like 'logic' or 'frameworks'). `variant` picks a
 * more specific icon for nodes with sub-types (middleware, workflow steps, gates).
 */
const ICONS: Record<string, LucideIcon> = {
  start: Play,
  stop: Square,
  logic: GitBranch,
  llm: Sparkles,
  master_agent: Bot,
  child_agent: BotMessageSquare,
  pipeline: Network,
  tool: Wrench,
  mcp: Plug,
  toolkit: Boxes,
  skill: Puzzle,
  synthetic_data: Database,
  connection: Link,
  frameworks: Layers,
  knowledge_base: Library,
  doc_loader: FileText,
  text_splitter: Scissors,
  embedding: Binary,
  vector_store: Database,
  retriever: Search,
  reranker: ListOrdered,
  memory: Brain,
  cache: Zap,
  middleware: ShieldCheck,
  human_gate: Hand,
  checkpointer: HardDriveDownload,
  wf_step: ListChecks,
  output_parser: Braces,
  gateway: Route,
}

const VARIANTS: Record<string, LucideIcon> = {
  'middleware:content_moderation': ShieldAlert,
  'middleware:cost_tracker': CircleDollarSign,
  'middleware:rate_limiter': Gauge,
  'middleware:prompt_injection': ShieldX,
  'middleware:grounding': ListChecks,
  'middleware:custom_rule': PenLine,
  'middleware:custom_pattern': Search,
  'human_gate:approval': UserCheck,
  'human_gate:edit': PenLine,
  'human_gate:review': Eye,
  'wf_step:ask': MessageCircleQuestion,
  'wf_step:choice': List,
  'wf_step:confirm': CircleCheck,
  'wf_step:tool_call': Plug,
  'wf_step:message': Megaphone,
}

interface Props {
  kind: string
  variant?: string
  size?: number
}

export function NodeIcon({ kind, variant, size = 14 }: Props) {
  const Icon = (variant && VARIANTS[`${kind}:${variant}`]) || ICONS[kind] || Square
  return <Icon size={size} strokeWidth={2} aria-hidden="true" focusable="false" />
}
