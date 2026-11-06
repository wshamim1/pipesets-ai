import { useEffect, useMemo, useRef, useState } from 'react'
import type { EvalRunRow } from './RunReport'

interface Props {
  runs: EvalRunRow[]   // any order; plotted oldest → newest
}

const H = 180
const PAD = { top: 12, right: 16, bottom: 26, left: 36 }

/** Pass rate across runs (one line, one hue) with a crosshair tooltip that snaps to the nearest run. */
export function PassRateTrend({ runs }: Props) {
  const ref = useRef<SVGSVGElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  // Draw at the real pixel width so text and strokes keep their size at any width
  const [W, setW] = useState(640)
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(240, Math.round(e.contentRect.width))))
    ro.observe(el)
    return () => ro.disconnect()
  }, [runs.length >= 2])   // the wrapper only mounts once there is a line to draw

  const pts = useMemo(() => {
    const sorted = [...runs].sort((a, b) => a.created_at.localeCompare(b.created_at))
    const n = sorted.length
    const iw = W - PAD.left - PAD.right
    const ih = H - PAD.top - PAD.bottom
    return sorted.map((r, i) => {
      const rate = r.total ? r.passed / r.total : 0
      return {
        run: r, rate,
        x: PAD.left + (n === 1 ? iw / 2 : (i / (n - 1)) * iw),
        y: PAD.top + (1 - rate) * ih,
      }
    })
  }, [runs, W])

  if (pts.length < 2) {
    return <div className="viz-empty">Run this dataset at least twice to see a trend.</div>
  }

  const path = pts.map((p, i) => `${i ? 'L' : 'M'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ')
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const box = ref.current!.getBoundingClientRect()
    const x = ((e.clientX - box.left) / box.width) * W
    let best = 0
    pts.forEach((p, i) => { if (Math.abs(p.x - x) < Math.abs(pts[best].x - x)) best = i })
    setHover(best)
  }
  const h = hover != null ? pts[hover] : null
  const last = pts[pts.length - 1]

  return (
    <div className="viz-trend" ref={wrapRef}>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${H}`}
        width={W}
        height={H}
        className="viz-trend-svg"
        role="img"
        aria-label={`Pass rate over ${pts.length} runs, latest ${Math.round(last.rate * 100)}%`}
        onPointerMove={onMove}
        onPointerLeave={() => setHover(null)}
      >
        {[0, 0.5, 1].map((g) => {
          const y = PAD.top + (1 - g) * (H - PAD.top - PAD.bottom)
          return (
            <g key={g}>
              <line x1={PAD.left} x2={W - PAD.right} y1={y} y2={y} className="viz-grid-line" />
              <text x={PAD.left - 6} y={y + 4} className="viz-axis-text" textAnchor="end">{g * 100}%</text>
            </g>
          )
        })}
        <text x={pts[0].x} y={H - 6} className="viz-axis-text" textAnchor="start">
          {new Date(pts[0].run.created_at).toLocaleDateString()}
        </text>
        <text x={last.x} y={H - 6} className="viz-axis-text" textAnchor="end">
          {new Date(last.run.created_at).toLocaleDateString()}
        </text>
        <path d={path} className="viz-line" />
        {pts.map((p, i) => (
          <circle key={p.run.id} cx={p.x} cy={p.y} r={4} className={`viz-dot${hover === i ? ' viz-dot--on' : ''}`} />
        ))}
        {/* direct label on the latest point only */}
        <text x={last.x} y={last.y - 10} className="viz-point-label" textAnchor="end">{Math.round(last.rate * 100)}%</text>
        {h && <line x1={h.x} x2={h.x} y1={PAD.top} y2={H - PAD.bottom} className="viz-crosshair" />}
      </svg>
      {h && (
        <div className="viz-tooltip" style={{ left: `${(h.x / W) * 100}%`, top: `${(h.y / H) * 100}%` }}>
          <strong>{Math.round(h.rate * 100)}%</strong>
          <span>{h.run.passed}/{h.run.total} passed · {h.run.app_version ? `v${h.run.app_version}` : 'draft'}</span>
          <span>{new Date(h.run.created_at).toLocaleString()}</span>
        </div>
      )}
    </div>
  )
}
