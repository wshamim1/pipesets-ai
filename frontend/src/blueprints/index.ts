import type { FlowEdge, FlowNode } from '../types'
import type { Blueprint } from './_types'
import { wireHandles } from './_helpers'

/**
 * Starter blueprints (Apps → Starter Blueprints): every file in this folder that exports ``BLUEPRINT`` is one,
 * so adding a blueprint is adding a file. Files starting with ``_`` hold shared types and helpers.
 * The dev server picks new files up by itself; Vitest's module cache may not — if a test still counts the old
 * number of blueprints after you add one, run ``npx vitest --clearCache``.
 */
const modules = import.meta.glob<{ BLUEPRINT?: Blueprint }>(['./*.ts', '!./_*.ts', '!./index.ts', '!./*.test.ts'], { eager: true })

export const STARTER_BLUEPRINTS: readonly Blueprint[] = Object.values(modules)
  .flatMap((m) => (m.BLUEPRINT ? [m.BLUEPRINT] : []))
  .sort((a, b) => a.order - b.order || a.name.localeCompare(b.name))

export type StarterBlueprint = Blueprint

export function buildBlueprintFlow(id: string): { nodes: FlowNode[]; edges: FlowEdge[] } {
  const blueprint = STARTER_BLUEPRINTS.find((b) => b.id === id)
  if (!blueprint) throw new Error(`Unknown blueprint '${id}'`)
  const { nodes, edges } = blueprint.build()
  return { nodes, edges: wireHandles(nodes, edges) }
}
