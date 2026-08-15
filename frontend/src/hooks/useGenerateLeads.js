/**
 * useGenerateLeads
 *
 * Manages the full lead-generation lifecycle:
 *
 *  NORMAL path  → POST /leads/generate-leads responds within 10 min
 *                  → setLeads(data.leads), setIsLoading(false)
 *
 *  TIMEOUT path → The 10-min AbortError fires (err.isPipelineTimeout === true)
 *                  → Switch to POLLING MODE:
 *                    · isLoading stays true so the button stays disabled
 *                    · isPolling = true so the UI can show a different message
 *                    · Every POLL_INTERVAL_MS we call GET /leads for the category
 *                    · We track the count returned each poll and show it live
 *                    · We stop polling when:
 *                        a) Two consecutive polls return the same count (pipeline done), OR
 *                        b) MAX_POLL_DURATION_MS has elapsed (safety ceiling — we show
 *                           whatever was saved so far)
 *
 * Exported state:
 *   leads          – array of lead docs (populated after pipeline finishes / polling stops)
 *   isLoading      – true while the POST is in flight OR while polling
 *   isPolling      – true only during the polling phase
 *   polledCount    – how many leads have been saved so far (live-updated during polling)
 *   elapsedSeconds – seconds since generate() was called (counts up while isLoading)
 *   isRefreshing   – true during a manual DB refresh (separate from generation)
 *   error          – null | string (only set for real errors, not pipeline timeouts)
 *   pipelineStats  – stats object from the last completed run
 *   generate()     – start a new generation run
 *   refresh()      – re-run last params
 *   refreshFromDB()– manual DB reload (no pipeline)
 *   clear()        – reset all state
 */

import { useState, useCallback, useRef, useEffect } from 'react'
import { generateLeads as generateLeadsApi, getLeads as getLeadsApi } from '../services/api'

const POLL_INTERVAL_MS    = 8_000   // poll every 8 s
const MAX_POLL_DURATION_MS = 30 * 60 * 1000  // give up after 30 min total

export function useGenerateLeads() {
  const [leads,          setLeads]          = useState([])
  const [isLoading,      setIsLoading]      = useState(false)
  const [isPolling,      setIsPolling]      = useState(false)
  const [polledCount,    setPolledCount]    = useState(0)
  const [elapsedSeconds, setElapsedSeconds] = useState(0)
  const [isRefreshing,   setIsRefreshing]   = useState(false)
  const [error,          setError]          = useState(null)
  const [lastParams,     setLastParams]     = useState(null)
  const [pipelineStats,  setPipelineStats]  = useState(null)

  // Refs for cleanup
  const pollTimerRef    = useRef(null)
  const elapsedTimerRef = useRef(null)
  const pollStartRef    = useRef(null)
  const lastCountRef    = useRef(0)
  const stableCountRef  = useRef(0) // consecutive polls with same count

  // ── Elapsed-seconds ticker (while isLoading) ──────────────────────────────
  const startElapsedTicker = useCallback(() => {
    setElapsedSeconds(0)
    const start = Date.now()
    elapsedTimerRef.current = setInterval(() => {
      setElapsedSeconds(Math.round((Date.now() - start) / 1000))
    }, 1000)
  }, [])

  const stopElapsedTicker = useCallback(() => {
    clearInterval(elapsedTimerRef.current)
    elapsedTimerRef.current = null
  }, [])

  // ── Stop polling (called on completion or safety ceiling) ─────────────────
  const stopPolling = useCallback(async (params) => {
    clearInterval(pollTimerRef.current)
    pollTimerRef.current = null
    setIsPolling(false)
    stopElapsedTicker()

    // Final fetch — grab whatever is in the DB for this category now
    try {
      const data = await getLeadsApi({
        ...(params?.industry ? { category: params.industry } : {}),
        per_page: 200,
        page: 1,
      })
      setLeads(data.leads ?? [])
      setPolledCount(data.total ?? 0)
    } catch {
      // Best-effort — leave whatever leads are already in state
    }
    setIsLoading(false)
  }, [stopElapsedTicker])

  // ── Polling loop — called once per interval ───────────────────────────────
  const runPoll = useCallback(async (params) => {
    // Safety ceiling
    if (Date.now() - pollStartRef.current > MAX_POLL_DURATION_MS) {
      await stopPolling(params)
      return
    }

    try {
      const data = await getLeadsApi({
        ...(params?.industry ? { category: params.industry } : {}),
        per_page: 200,
        page: 1,
      })
      const currentCount = data.total ?? 0
      setPolledCount(currentCount)
      setLeads(data.leads ?? [])

      // Check stability — two identical counts in a row = pipeline done
      if (currentCount === lastCountRef.current && currentCount > 0) {
        stableCountRef.current += 1
        if (stableCountRef.current >= 2) {
          await stopPolling(params)
          return
        }
      } else {
        stableCountRef.current = 0
      }
      lastCountRef.current = currentCount
    } catch {
      // Ignore transient poll errors — keep trying
    }
  }, [stopPolling])

  // ── Enter polling mode (called after a timeout error) ────────────────────
  const startPolling = useCallback((params) => {
    setIsPolling(true)
    pollStartRef.current = Date.now()
    lastCountRef.current = 0
    stableCountRef.current = 0
    setPolledCount(0)

    // Run immediately then on interval
    runPoll(params)
    pollTimerRef.current = setInterval(() => runPoll(params), POLL_INTERVAL_MS)
  }, [runPoll])

  // ── Cleanup on unmount ────────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      clearInterval(pollTimerRef.current)
      clearInterval(elapsedTimerRef.current)
    }
  }, [])

  // ── Main generate function ────────────────────────────────────────────────
  const generate = useCallback(async (params) => {
    // Clear any previous polling
    clearInterval(pollTimerRef.current)
    pollTimerRef.current = null

    setIsLoading(true)
    setIsPolling(false)
    setError(null)
    setLastParams(params)
    setPipelineStats(null)
    setLeads([])
    setPolledCount(0)
    startElapsedTicker()

    try {
      const data = await generateLeadsApi(params)
      setLeads(data.leads ?? [])
      setPipelineStats(data.pipeline_stats ?? null)
      stopElapsedTicker()
      setIsLoading(false)
    } catch (err) {
      if (err.isPipelineTimeout) {
        // ── TIMEOUT PATH: switch to polling instead of showing error ──────
        // isLoading stays true — button stays disabled
        // The elapsed ticker keeps running so the UI updates live
        startPolling(params)
      } else {
        // Real network/server error — show it
        stopElapsedTicker()
        setError(err.message ?? 'Something went wrong. Please try again.')
        setLeads([])
        setPipelineStats(null)
        setIsLoading(false)
      }
    }
  }, [startElapsedTicker, stopElapsedTicker, startPolling])

  /** Re-run the last generate request. */
  const refresh = useCallback(() => {
    if (lastParams) generate(lastParams)
  }, [lastParams, generate])

  /** Reload leads directly from MongoDB — no pipeline. */
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

  /** Clear all state and stop any in-progress polling. */
  const clear = useCallback(() => {
    clearInterval(pollTimerRef.current)
    pollTimerRef.current = null
    stopElapsedTicker()
    setLeads([])
    setError(null)
    setLastParams(null)
    setPipelineStats(null)
    setIsLoading(false)
    setIsPolling(false)
    setPolledCount(0)
    setElapsedSeconds(0)
  }, [stopElapsedTicker])

  return {
    leads,
    isLoading,
    isPolling,
    polledCount,
    elapsedSeconds,
    isRefreshing,
    error,
    lastParams,
    pipelineStats,
    generate,
    refresh,
    refreshFromDB,
    clear,
  }
}
