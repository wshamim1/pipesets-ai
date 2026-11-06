import { useEffect } from 'react'

const MOD = typeof navigator !== 'undefined' && /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘' : 'Ctrl'

// Keep in step with the handlers: canvas shortcuts in App.tsx, ⌘K in Sidebar.tsx, ⌘↵ in PromptRunner / the prompt bar
const GROUPS: { title: string; rows: [string[], string][] }[] = [
  {
    title: 'Canvas',
    rows: [
      [[MOD, 'Z'], 'Undo'],
      [[MOD, '⇧', 'Z'], 'Redo'],
      [[MOD, 'C'], 'Copy selected nodes'],
      [[MOD, 'V'], 'Paste'],
      [[MOD, 'D'], 'Duplicate selected nodes'],
      [['⌫'], 'Delete selected node or edge'],
    ],
  },
  {
    title: 'Build',
    rows: [
      [[MOD, 'K'], 'Search nodes, tools and models'],
      [[MOD, '↵'], 'Generate from the prompt bar'],
      [[MOD, '↵'], 'Run the prompt in the Run panel'],
    ],
  },
  {
    title: 'Anywhere',
    rows: [
      [['?'], 'Show this list'],
      [['Esc'], 'Close a dialog, menu or drawer'],
    ],
  },
]

/** Help → Keyboard shortcuts (also opened with "?"). */
export function KeyboardShortcutsPanel({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="modal-backdrop" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="modal-card shortcuts-card" role="dialog" aria-modal="true" aria-labelledby="shortcuts-title">
        <div className="modal-header">
          <h3 id="shortcuts-title">Keyboard shortcuts</h3>
          <button type="button" className="modal-close-btn" aria-label="Close" onClick={onClose}>✕</button>
        </div>
        <div className="about-body">
          {GROUPS.map((g) => (
            <section key={g.title} aria-label={g.title}>
              <h4>{g.title}</h4>
              <dl className="shortcuts-list">
                {g.rows.map(([keys, what]) => (
                  <div key={what} className="shortcuts-row">
                    <dt>{what}</dt>
                    <dd>{keys.map((k) => <kbd key={k}>{k}</kbd>)}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <p className="about-hint shortcuts-note">Canvas shortcuts work when the canvas has focus, so text fields keep their own.</p>
        </div>
      </div>
    </div>
  )
}
