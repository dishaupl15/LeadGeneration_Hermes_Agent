/**
 * useGenerateLeads
 *
 * Custom hook that encapsulates all state for the lead generation flow:
 *   - isLoading  → show spinner / disable button
 *   - error      → show error banner with message
 *   - leads      → array of MongoDB lead documents to render in the table
 *   - lastParams → remember what was last requested (for Refresh)
 *   - pipelineStats → stats from the last run (Google Maps, CompanyEnrich, Serper, Firecrawl)
 *
 * Usage:
 *   const { leads, isLoading, error, generate, refresh, clear, pipelineStats } = useGenerateLeads()
 */

import { useState, useCallback } from 'react'
import { generateLeads as generateLeadsApi, getLeads as getLeadsApi } from '../services/api'

export function useGenerateLeads() {
  const [leads, setLeads]               = useState([])
  const [isLoading, setIsLoading]       = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError]               = useState(null)      // null | string
  const [lastParams, setLastParams]     = useState(null)      // null | { industry, state, district, target }
  const [pipelineStats, setPipelineStats] = useState(null)    // null | object

  /**
   * Fire the POST /leads/generate-leads request (Google Maps-first pipeline).
   * @param {{ industry: string, state: string, district?: string, target?: number }} params
   */
  const generate = useCallback(async (params) => {
    setIsLoading(true)
    setError(null)
    setLastParams(params)
    setPipelineStats(null)

    try {
      const data = await generateLeadsApi(params)
      // Backend returns actual MongoDB documents in data.leads
      setLeads(data.leads ?? [])
      setPipelineStats(data.pipeline_stats ?? null)
    } catch (err) {
      setError(err.message ?? 'Something went wrong. Please try again.')
      setLeads([])
      setPipelineStats(null)
    } finally {
      setIsLoading(false)
    }
  }, [])

  /**
   * Re-run the last generate request (re-triggers Hermes).
   * Does nothing if generate() was never called.
   */
  const refresh = useCallback(() => {
    if (lastParams) generate(lastParams)
  }, [lastParams, generate])

  /**
   * Reload leads directly from MongoDB via GET /leads.
   * No Hermes. No AI. Just a plain DB read.
   */
  const refreshFromDB = useCallback(async () => {
    setIsRefreshing(true)
    setError(null)
    try {
      const data = await getLeadsApi()
      setLeads(data.leads ?? [])
    } catch (err) {
      setError(err.message ?? 'Failed to refresh leads from the database.')
    } finally {
      setIsRefreshing(false)
    }
  }, [])

  /**
   * Clear all state (reset the table to empty).
   */
  const clear = useCallback(() => {
    setLeads([])
    setError(null)
    setLastParams(null)
  }, [])

  return { leads, isLoading, isRefreshing, error, lastParams, pipelineStats, generate, refresh, refreshFromDB, clear }
}
