/**
 * useSidebarState — manages all sidebar accordion open/close toggles.
 */
import { useState } from 'react'
import type { CustomToolRecord } from '../components/CustomToolModal'

export function useSidebarState() {
  const [isGeneralSectionOpen, setIsGeneralSectionOpen] = useState(false)
  const [isLlmSectionOpen, setIsLlmSectionOpen] = useState(false)
  const [isToolsSectionOpen, setIsToolsSectionOpen] = useState(false)
  const [isMcpSectionOpen, setIsMcpSectionOpen] = useState(false)
  const [isToolkitSectionOpen, setIsToolkitSectionOpen] = useState(false)
  const [isMemorySectionOpen, setIsMemorySectionOpen] = useState(false)
  const [isCacheSectionOpen, setIsCacheSectionOpen] = useState(false)
  const [isDocLoaderSectionOpen, setIsDocLoaderSectionOpen] = useState(false)
  const [isTextSplitterSectionOpen, setIsTextSplitterSectionOpen] = useState(false)
  const [isEmbeddingSectionOpen, setIsEmbeddingSectionOpen] = useState(false)
  const [isVectorStoreSectionOpen, setIsVectorStoreSectionOpen] = useState(false)
  const [isRetrieverSectionOpen, setIsRetrieverSectionOpen] = useState(false)
  const [isAgentsSectionOpen, setIsAgentsSectionOpen] = useState(false)
  const [isCustomToolsSectionOpen, setIsCustomToolsSectionOpen] = useState(false)
  const [isConnectionsSectionOpen, setIsConnectionsSectionOpen] = useState(false)
  const [isKnowledgeBaseSectionOpen, setIsKnowledgeBaseSectionOpen] = useState(false)
  const [isPipelinesSectionOpen, setIsPipelinesSectionOpen] = useState(false)
  const [isSkillsSectionOpen, setIsSkillsSectionOpen] = useState(false)
  const [isFrameworksSectionOpen, setIsFrameworksSectionOpen] = useState(false)
  const [isSyntheticDataSectionOpen, setIsSyntheticDataSectionOpen] = useState(false)
  const [isRerankerSectionOpen, setIsRerankerSectionOpen] = useState(false)
  const [isHumanGateSectionOpen, setIsHumanGateSectionOpen] = useState(false)
  const [isCheckpointerSectionOpen, setIsCheckpointerSectionOpen] = useState(false)
  const [isWorkflowSectionOpen, setIsWorkflowSectionOpen] = useState(false)
  const [isOutputParserSectionOpen, setIsOutputParserSectionOpen] = useState(false)
  const [isMiddlewareSectionOpen, setIsMiddlewareSectionOpen] = useState(false)

  // Custom tool modal state
  const [customTools, setCustomTools] = useState<CustomToolRecord[]>([])
  const [customToolModalOpen, setCustomToolModalOpen] = useState(false)
  const [editingCustomTool, setEditingCustomTool] = useState<CustomToolRecord | undefined>(undefined)

  // Sidebar search / filter state
  const [collapsedProviders, setCollapsedProviders] = useState<Record<string, boolean>>({})
  const [searchModelQuery, setSearchModelQuery] = useState('')
  const [searchToolQuery, setSearchToolQuery] = useState('')
  const [searchMcpQuery, setSearchMcpQuery] = useState('')

  return {
    isGeneralSectionOpen, setIsGeneralSectionOpen,
    isLlmSectionOpen, setIsLlmSectionOpen,
    isToolsSectionOpen, setIsToolsSectionOpen,
    isMcpSectionOpen, setIsMcpSectionOpen,
    isToolkitSectionOpen, setIsToolkitSectionOpen,
    isMemorySectionOpen, setIsMemorySectionOpen,
    isCacheSectionOpen, setIsCacheSectionOpen,
    isDocLoaderSectionOpen, setIsDocLoaderSectionOpen,
    isTextSplitterSectionOpen, setIsTextSplitterSectionOpen,
    isEmbeddingSectionOpen, setIsEmbeddingSectionOpen,
    isVectorStoreSectionOpen, setIsVectorStoreSectionOpen,
    isRetrieverSectionOpen, setIsRetrieverSectionOpen,
    isAgentsSectionOpen, setIsAgentsSectionOpen,
    isCustomToolsSectionOpen, setIsCustomToolsSectionOpen,
    isConnectionsSectionOpen, setIsConnectionsSectionOpen,
    isKnowledgeBaseSectionOpen, setIsKnowledgeBaseSectionOpen,
    isPipelinesSectionOpen, setIsPipelinesSectionOpen,
    isSkillsSectionOpen, setIsSkillsSectionOpen,
    isFrameworksSectionOpen, setIsFrameworksSectionOpen,
    isSyntheticDataSectionOpen, setIsSyntheticDataSectionOpen,
    isRerankerSectionOpen, setIsRerankerSectionOpen,
    isHumanGateSectionOpen, setIsHumanGateSectionOpen,
    isCheckpointerSectionOpen, setIsCheckpointerSectionOpen,
    isWorkflowSectionOpen, setIsWorkflowSectionOpen,
    isOutputParserSectionOpen, setIsOutputParserSectionOpen,
    isMiddlewareSectionOpen, setIsMiddlewareSectionOpen,
    customTools, setCustomTools,
    customToolModalOpen, setCustomToolModalOpen,
    editingCustomTool, setEditingCustomTool,
    collapsedProviders, setCollapsedProviders,
    searchModelQuery, setSearchModelQuery,
    searchToolQuery, setSearchToolQuery,
    searchMcpQuery, setSearchMcpQuery,
  }
}
