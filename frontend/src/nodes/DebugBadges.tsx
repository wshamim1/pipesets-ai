import type { DebugNodeFields } from '../types'

/**
 * The node's own debug buttons (editor-only debugging, plan.md F6), at the card's top-left corner:
 * ● toggles a breakpoint (Prompt Runner runs pause before this node), 📌 opens the node's Debug
 * section to pin an output or change / remove the pin. Both stay visible while set; otherwise they
 * show on hover or when the node is selected. Child agents can be pinned but not paused.
 */
export function DebugBadges({ data, canPause = true }: { data: DebugNodeFields; canPause?: boolean }) {
  const editable = !!data.onDebugUpdate
  if (!editable && !data.debug_breakpoint && !data.debug_pin) return null
  const pin = data.debug_pin
  return (
    <span className="node-debug-badges nodrag" onClick={(e) => e.stopPropagation()} onDoubleClick={(e) => e.stopPropagation()}>
      {canPause && (editable || data.debug_breakpoint) && (
        <button type="button"
          className={`node-debug-badge node-debug-badge--break${data.debug_breakpoint ? ' node-debug-badge--on' : ''}`}
          aria-pressed={!!data.debug_breakpoint} disabled={!editable}
          title={data.debug_breakpoint
            ? 'Breakpoint: Prompt Runner runs pause before this node. Click to remove'
            : 'Add a breakpoint: Prompt Runner runs pause before this node'}
          onClick={() => data.onDebugUpdate?.({ debug_breakpoint: data.debug_breakpoint ? undefined : true })}>
          ●
        </button>
      )}
      {(editable || pin) && (
        <button type="button"
          className={`node-debug-badge node-debug-badge--pin${pin ? ' node-debug-badge--on' : ''}`}
          aria-pressed={!!pin} disabled={!data.onOpenDebug}
          title={pin
            ? `Pinned output — used instead of running this node. Click to edit or unpin:\n${pin.output.slice(0, 200)}`
            : 'Pin an output: use it instead of running this node'}
          onClick={() => data.onOpenDebug?.(!pin)}>
          📌
        </button>
      )}
    </span>
  )
}
