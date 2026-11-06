import { BaseEdge, EdgeLabelRenderer, getBezierPath, useReactFlow } from '@xyflow/react'
import type { EdgeProps, EdgeTypes } from '@xyflow/react'

/**
 * Default bezier edge plus a small × at its midpoint while the edge is
 * selected. Keyboard delete (Backspace / Delete) still works.
 */
export function DeletableEdge({
  id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition,
  markerEnd, style, label, selected, deletable,
}: EdgeProps) {
  const { deleteElements } = useReactFlow()
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })

  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={style}
        label={label} labelX={labelX} labelY={labelY - (label ? 18 : 0)}
        labelShowBg labelBgPadding={[4, 2]} labelBgBorderRadius={4} />
      {selected && deletable !== false && (
        <EdgeLabelRenderer>
          <button
            type="button"
            className="edge-delete-btn nodrag nopan"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)` }}
            title="Delete connection"
            onClick={(e) => { e.stopPropagation(); deleteElements({ edges: [{ id }] }) }}
          >
            ×
          </button>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

export const edgeTypes: EdgeTypes = {
  deletable: DeletableEdge,
}
