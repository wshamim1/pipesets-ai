import { createContext, useContext, useState, type ReactNode } from 'react'

interface ExecutionContextValue {
  executingNodeIds: string[]
  setExecutingNodeIds: (ids: string[] | ((prev: string[]) => string[])) => void
  isExecuting: boolean
}

const ExecutionContext = createContext<ExecutionContextValue>({
  executingNodeIds: [],
  setExecutingNodeIds: () => {},
  isExecuting: false,
})

export function ExecutionProvider({ children }: { children: ReactNode }) {
  const [executingNodeIds, setExecutingNodeIds] = useState<string[]>([])

  return (
    <ExecutionContext.Provider
      value={{
        executingNodeIds,
        setExecutingNodeIds,
        isExecuting: executingNodeIds.length > 0,
      }}
    >
      {children}
    </ExecutionContext.Provider>
  )
}

export function useExecution() {
  return useContext(ExecutionContext)
}
