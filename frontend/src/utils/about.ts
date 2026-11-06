import { API_BASE } from '../types'

/** Settings → About: the server's info (GET /api/about) and what this UI bundle was built with (vite.config.ts). */
export interface Library { name: string; version: string; role: string }

export interface ServerAbout {
  app: { name: string; version: string; license: string;
         commit: { short: string; hash: string; date: string; subject: string } | null }
  backend: { python: string; implementation: string; platform: string; frozen: boolean; libraries: Library[];
             database: { type: string; driver: string; version: string }; llm_backends: string[] }
  catalog: { tools: number; mcp_servers: number; frameworks: number; agents: number; starter_roles: number; skills: number }
}

export interface FrontendBuild { builtAt: string; libraries: Library[] }

declare const __FRONTEND_BUILD__: FrontendBuild | undefined

export const FRONTEND_BUILD: FrontendBuild =
  typeof __FRONTEND_BUILD__ !== 'undefined' ? __FRONTEND_BUILD__ : { builtAt: '', libraries: [] }

export async function fetchAbout(): Promise<ServerAbout> {
  const res = await fetch(`${API_BASE}/api/about`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
