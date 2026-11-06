import type { FlowEdge, FlowNode } from '../types'

/** A starter blueprint: one file per blueprint in src/blueprints/, each exporting ``BLUEPRINT``. */
export interface Blueprint {
  id: string
  name: string
  description: string
  /** Category chip on Apps → Starter Blueprints */
  badge: string
  icon: string
  /** Position in the gallery (lower first) */
  order: number
  /** The flow a clone starts from */
  build: () => { nodes: FlowNode[]; edges: FlowEdge[] }
}
