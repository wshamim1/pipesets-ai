import { useState, useCallback } from 'react'
import { API_BASE } from '../types'

type FrameworkHint = 'auto' | 'langchain' | 'crewai' | 'autogen' | 'python' | 'other'

interface LlmConfigShape {
  provider: string
  model: string
  api_key?: string
  base_url?: string
}

const FRAMEWORK_OPTIONS: { value: FrameworkHint; label: string; icon: string }[] = [
  { value: 'auto',      label: 'Auto-detect',  icon: '🔍' },
  { value: 'langchain', label: 'LangChain',    icon: '🦜' },
  { value: 'crewai',    label: 'CrewAI',       icon: '🚢' },
  { value: 'autogen',   label: 'AutoGen',      icon: '🤖' },
  { value: 'python',    label: 'Plain Python', icon: '🐍' },
  { value: 'other',     label: 'Other',        icon: '📄' },
]

const EXAMPLE_SNIPPETS: Record<FrameworkHint, string> = {
  auto: '',
  langchain: `from langchain.chat_models import ChatOpenAI
from langchain.tools import DuckDuckGoSearchRun
from langchain.agents import initialize_agent, AgentType
from langchain.memory import ConversationBufferMemory

llm = ChatOpenAI(model="gpt-4o", temperature=0.7)
search = DuckDuckGoSearchRun()
memory = ConversationBufferMemory(memory_key="chat_history")

agent = initialize_agent(
    tools=[search],
    llm=llm,
    agent=AgentType.CONVERSATIONAL_REACT_DESCRIPTION,
    memory=memory,
    verbose=True,
)
agent.run("What are the latest AI news?")`,
  crewai: `from crewai import Agent, Task, Crew

researcher = Agent(
    role="Senior Research Analyst",
    goal="Uncover cutting-edge developments in AI",
    backstory="You are an expert at finding and summarizing AI research.",
    tools=[search_tool],
    llm="gpt-4o",
)
writer = Agent(
    role="Tech Content Strategist",
    goal="Craft compelling content on tech advancements",
    backstory="You are a skilled writer who turns research into readable articles.",
    llm="gpt-4o",
)
research_task = Task(description="Research the latest AI trends", agent=researcher)
write_task = Task(description="Write a blog post from the research", agent=writer)
crew = Crew(agents=[researcher, writer], tasks=[research_task, write_task])
result = crew.kickoff()`,
  autogen: `import autogen

config_list = [{"model": "gpt-4o", "api_key": "YOUR_KEY"}]

assistant = autogen.AssistantAgent("assistant", llm_config={"config_list": config_list})
user_proxy = autogen.UserProxyAgent("user_proxy", human_input_mode="NEVER",
    code_execution_config={"work_dir": "coding"})

user_proxy.initiate_chat(assistant, message="Write a Python script to fetch weather data.")`,
  python: `import openai

client = openai.OpenAI()

def run_agent(prompt: str) -> str:
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content

print(run_agent("Explain quantum computing in simple terms."))`,
  other: '',
}

interface Props {
  onClose: () => void
  onImport: (blueprint: any, message: string) => void
  llmConfig?: LlmConfigShape
}

export function ImportCodeModal({ onClose, onImport, llmConfig }: Props) {
  const [code, setCode] = useState('')
  const [frameworkHint, setFrameworkHint] = useState<FrameworkHint>('auto')
  const [isImporting, setIsImporting] = useState(false)
  const [statusMsg, setStatusMsg] = useState('')
  const [statusType, setStatusType] = useState<'idle' | 'success' | 'error' | 'warn'>('idle')

  const handleLoadExample = useCallback(() => {
    const snippet = EXAMPLE_SNIPPETS[frameworkHint] || EXAMPLE_SNIPPETS.langchain
    setCode(snippet)
    setStatusMsg('')
  }, [frameworkHint])

  const handleImport = useCallback(async () => {
    if (!code.trim() || isImporting) return
    setIsImporting(true)
    setStatusMsg('Analysing code and generating pipeline…')
    setStatusType('idle')

    try {
      const res = await fetch(`${API_BASE}/api/build/import-code`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code,
          framework_hint: frameworkHint,
          config: llmConfig ?? undefined,
        }),
      })

      const data = await res.json()

      if (!data.success) {
        setStatusMsg(data.message || 'Import failed.')
        setStatusType('error')
        return
      }

      const hasBlueprint = data.blueprint && Array.isArray(data.blueprint.nodes) && data.blueprint.nodes.length >= 2

      if (!hasBlueprint) {
        setStatusMsg(data.message || 'No pipeline could be generated — try adding more context.')
        setStatusType('warn')
        return
      }

      setStatusType('success')
      onImport(data.blueprint, data.message || 'Pipeline imported successfully.')
    } catch (e: any) {
      setStatusMsg(`Request failed: ${e.message}`)
      setStatusType('error')
    } finally {
      setIsImporting(false)
    }
  }, [code, frameworkHint, isImporting, llmConfig, onImport])

  const statusColors = {
    idle:    { bg: '#f8fafc', color: '#475569', border: '#e2e8f0' },
    success: { bg: '#f0fdf4', color: '#15803d', border: '#bbf7d0' },
    error:   { bg: '#fef2f2', color: '#b91c1c', border: '#fecaca' },
    warn:    { bg: '#fffbeb', color: '#92400e', border: '#fde68a' },
  }
  const sc = statusColors[statusType]

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.45)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9000,
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div style={{
        background: '#fff', borderRadius: 10, width: 740, maxWidth: '96vw',
        maxHeight: '90vh', display: 'flex', flexDirection: 'column',
        boxShadow: '0 20px 60px rgba(0,0,0,0.25)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '14px 20px', borderBottom: '1px solid #e5e7eb',
        }}>
          <div>
            <div style={{ fontWeight: 700, fontSize: 15, color: '#1f2328' }}>
              ↩ Import Code → Pipeline
            </div>
            <div style={{ fontSize: 12, color: '#57606a', marginTop: 2 }}>
              Paste LangChain, CrewAI, AutoGen, or plain Python — we'll scaffold the canvas pipeline automatically.
            </div>
          </div>
          <button
            type="button" onClick={onClose}
            style={{ background: 'none', border: 'none', fontSize: 18, cursor: 'pointer', color: '#57606a', lineHeight: 1 }}
          >✕</button>
        </div>

        {/* Framework picker */}
        <div style={{ padding: '12px 20px 0', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {FRAMEWORK_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => setFrameworkHint(opt.value)}
              style={{
                padding: '4px 12px', borderRadius: 20, fontSize: 12, cursor: 'pointer',
                fontWeight: frameworkHint === opt.value ? 600 : 400,
                background: frameworkHint === opt.value ? '#1d4ed8' : '#f1f5f9',
                color: frameworkHint === opt.value ? '#fff' : '#475569',
                border: frameworkHint === opt.value ? '1px solid #1d4ed8' : '1px solid #e2e8f0',
                transition: 'all 0.12s',
              }}
            >
              {opt.icon} {opt.label}
            </button>
          ))}
          <button
            type="button"
            onClick={handleLoadExample}
            style={{
              marginLeft: 'auto', padding: '4px 12px', borderRadius: 20, fontSize: 12,
              cursor: 'pointer', background: '#f0fdf4', color: '#15803d',
              border: '1px solid #bbf7d0', fontWeight: 500,
            }}
          >
            Load example
          </button>
        </div>

        {/* Code textarea */}
        <div style={{ padding: '10px 20px', flex: 1, minHeight: 0 }}>
          <textarea
            value={code}
            onChange={(e) => { setCode(e.target.value); setStatusMsg('') }}
            placeholder={`Paste your ${frameworkHint === 'auto' ? 'agent / LLM' : frameworkHint} code here…\n\nSupported: LangChain chains/agents, CrewAI crews, AutoGen conversations, plain Python openai/anthropic calls, custom tool wrappers, RAG pipelines…`}
            spellCheck={false}
            style={{
              width: '100%', height: 320, fontFamily: 'monospace', fontSize: 12.5,
              border: '1px solid #e2e8f0', borderRadius: 6, padding: '10px 12px',
              resize: 'vertical', background: '#0f172a', color: '#e2e8f0',
              lineHeight: 1.55, boxSizing: 'border-box', outline: 'none',
            }}
          />
          <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 4 }}>
            {code.length > 0
              ? `${code.length.toLocaleString()} chars · ${code.split('\n').length} lines${code.length > 12000 ? ' (first 12 000 chars will be analysed)' : ''}`
              : 'Up to ~12 000 chars analysed in one pass'}
          </div>
        </div>

        {/* Status */}
        {statusMsg && (
          <div style={{
            margin: '0 20px', padding: '8px 12px', borderRadius: 6, fontSize: 12,
            background: sc.bg, color: sc.color, border: `1px solid ${sc.border}`,
          }}>
            {statusType === 'success' && '✅ '}
            {statusType === 'error'   && '⚠ '}
            {statusType === 'warn'    && '⚠ '}
            {statusMsg}
          </div>
        )}

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'flex-end',
          gap: 10, padding: '14px 20px', borderTop: '1px solid #e5e7eb', marginTop: 10,
        }}>
          <div style={{ fontSize: 11, color: '#94a3b8', marginRight: 'auto' }}>
            Requires an active LLM API key (OpenAI, Anthropic, etc.) configured on the LLM node.
          </div>
          <button
            type="button" onClick={onClose}
            style={{
              padding: '6px 16px', borderRadius: 6, fontSize: 13, cursor: 'pointer',
              background: '#f1f5f9', color: '#475569', border: '1px solid #e2e8f0',
            }}
          >
            Cancel
          </button>
          <button
            type="button" onClick={handleImport}
            disabled={!code.trim() || isImporting}
            style={{
              padding: '6px 18px', borderRadius: 6, fontSize: 13, fontWeight: 600,
              cursor: !code.trim() || isImporting ? 'not-allowed' : 'pointer',
              background: !code.trim() || isImporting ? '#93c5fd' : '#1d4ed8',
              color: '#fff', border: 'none',
            }}
          >
            {isImporting ? '⏳ Importing…' : '↩ Import as Pipeline'}
          </button>
        </div>
      </div>
    </div>
  )
}
