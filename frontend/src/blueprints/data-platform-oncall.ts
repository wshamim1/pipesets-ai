import type { FlowNode } from '../types'
import type { Blueprint } from './_types'
import { edge, llm, start, stop, tool } from './_helpers'

const snowflake = { account: '', token: '', token_type: 'pat', warehouse: '', database: '', schema: '', role: '' }
const kafka = { base_url: 'http://localhost:8082', rest_path: '/kafka/v3', cluster_id: '', api_key: '', api_secret: '' }

export const BLUEPRINT: Blueprint = {
  id: 'tpl-data-platform-oncall',
  name: 'Data Platform On-Call (2 Skills)',
  description: 'One on-call LLM with the Snowflake query-review and Kafka lag skills; each loads (with its tools) only when a question needs it.',
  badge: 'Skills',
  icon: '🛰️',
  order: 240,
  build() {
    const skill = (id: string, x: number, label: string, skill_id: string, icon: string, description: string, tool_ids: string[]): FlowNode =>
      ({ id, type: 'skill', position: { x, y: 60 }, data: {
        label, skill_id, icon, description, instructions: '', category: 'data-platform', tool_ids, tags: [] } }) as unknown as FlowNode
    const nodes: FlowNode[] = [
      start(),
      { id: 'llm-1', type: 'llm', position: { x: 340, y: 300 }, data: {
        ...llm('Data On-Call',
          'You are the data platform on-call assistant. Load the skill that matches the question (Snowflake cost or speed, '
          + 'Kafka lag), then answer from the evidence your tools return. Never resize warehouses or reset offsets.', 0.2),
        skill_mode: 'on_demand', max_active_skills: 2,
      }},
      skill('skill-snowflake', 340, 'Snowflake query review', 'skill_snowflake_query_review', '❄️',
        'When the user asks why Snowflake queries are slow or expensive.', ['snowflake_query_history', 'snowflake_warehouses', 'snowflake_reader']),
      skill('skill-kafka', 600, 'Kafka consumer lag', 'skill_kafka_lag', '📨',
        'When the user asks why a Kafka consumer group is lagging, stuck or rebalancing.', ['kafka_consumer_lag', 'kafka_topics', 'kafka_connectors']),
      tool('tool-sf-history', 340, 520, 'Snowflake Query History', 'snowflake_query_history', '🕘', 'Recent queries with status, duration and errors.',
        { ...snowflake, limit: 20 }),
      tool('tool-sf-wh', 600, 520, 'Snowflake Warehouses', 'snowflake_warehouses', '🏭', 'Warehouse state, size and auto-suspend.', snowflake),
      tool('tool-sf-reader', 860, 520, 'Snowflake Reader', 'snowflake_reader', '❄️', 'Runs one read-only statement (e.g. EXPLAIN).',
        { account: '', user: '', password: '', warehouse: '', database: '', schema: '', role: '', max_results: 50 }),
      tool('tool-k-lag', 1120, 520, 'Kafka Consumer Lag', 'kafka_consumer_lag', '⏱️', 'A consumer group\'s lag per topic and partition.', kafka),
      tool('tool-k-topics', 1380, 520, 'Kafka Topics', 'kafka_topics', '🧵', 'Topics, partitions and settings.', { ...kafka, max_results: 50 }),
      tool('tool-k-connect', 1640, 520, 'Kafka Connect', 'kafka_connectors', '🔌', 'Connectors and their failed tasks.',
        { base_url: 'http://localhost:8083', api_key: '', api_secret: '' }),
      stop(700),
    ]
    const toolIds = ['tool-sf-history', 'tool-sf-wh', 'tool-sf-reader', 'tool-k-lag', 'tool-k-topics', 'tool-k-connect']
    const edges = [
      edge('e-start-llm', 'start-1', 'llm-1'),
      edge('e-snowflake-llm', 'skill-snowflake', 'llm-1'),
      edge('e-kafka-llm', 'skill-kafka', 'llm-1'),
      ...toolIds.map((t) => edge(`e-llm-${t}`, 'llm-1', t)),
      edge('e-llm-stop', 'llm-1', 'stop-1'),
    ]
    return { nodes, edges }
  },
}
