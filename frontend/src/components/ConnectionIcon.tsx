import { Cloud, Database, Globe, HardDrive, Leaf, Link, MemoryStick, Snowflake } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

/**
 * Line icon for a connection, keyed by connection type and tinted with the
 * provider's colour — matches the NodeIcon set instead of stored emojis.
 */
const CONNECTION_ICONS: Record<string, { icon: LucideIcon; color: string }> = {
  postgres:   { icon: Database,    color: '#336791' },
  postgresql: { icon: Database,    color: '#336791' },
  mysql:      { icon: Database,    color: '#00758f' },
  mongodb:    { icon: Leaf,        color: '#13aa52' },
  redis:      { icon: MemoryStick, color: '#dc382d' },
  snowflake:  { icon: Snowflake,   color: '#29b5e8' },
  aws_s3:     { icon: Cloud,       color: '#e47911' },
  sqlite:     { icon: HardDrive,   color: '#0f5f85' },
  custom_api: { icon: Globe,       color: '#6366f1' },
}

interface Props {
  type: string
  size?: number
}

export function ConnectionIcon({ type, size = 12 }: Props) {
  const { icon: Icon, color } = CONNECTION_ICONS[type?.toLowerCase()] ?? { icon: Link, color: '#64748b' }
  return (
    <span
      className="connection-icon"
      style={{ color, background: `${color}14`, width: size + 6, height: size + 6 }}
    >
      <Icon size={size} strokeWidth={2} aria-hidden="true" focusable="false" />
    </span>
  )
}
