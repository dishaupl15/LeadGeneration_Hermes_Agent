/**
 * useGoogleMapsLeads
 *
 * Custom hook for the Google Maps lead-discovery flow.
 * Manages states list, dynamic districts, and search results.
 *
 * Usage:
 *   const {
 *     states, districts, loadingStates, loadingDistricts,
 *     businesses, isLoading, error, stats,
 *     selectedState, selectedDistrict, target, excludeSeen,
 *     setSelectedState, setSelectedDistrict, setTarget, setExcludeSeen,
 *     search, clear,
 *   } = useGoogleMapsLeads()
 */

import { useState, useCallback, useEffect } from 'react'
import {
  getMapsStates,
  getMapsDistricts,
  generateMapsLeads,
} from '../services/api'

export function useGoogleMapsLeads() {
  // ── Geography options ──────────────────────────────────────────
  const [states, setStates]               = useState([])
  const [districts, setDistricts]         = useState([])
  const [loadingStates, setLoadingStates] = useState(false)
  const [loadingDistricts, setLoadingDistricts] = useState(false)

  // ── User selections ────────────────────────────────────────────
  const [selectedState, setSelectedState]       = useState('')
  const [selectedDistrict, setSelectedDistrict] = useState('')
  const [target, setTarget]                     = useState(50)
  const [excludeSeen, setExcludeSeen]           = useState(true)

  // ── Results ────────────────────────────────────────────────────
  const [businesses, setBusinesses]       = useState([])
  const [stats, setStats]                 = useState(null)
  const [pipelineStats, setPipelineStats] = useState(null)
  const [isLoading, setIsLoading]         = useState(false)
  const [error, setError]           = useState(null)

  // ── Load states once on mount ──────────────────────────────────
  useEffect(() => {
    setLoadingStates(true)
    getMapsStates()
      .then((data) => setStates(data.states ?? []))
      .catch(() => setStates([]))
      .finally(() => setLoadingStates(false))
  }, [])

  // ── Load districts whenever selectedState changes ──────────────
  useEffect(() => {
    if (!selectedState) {
      setDistricts([])
      setSelectedDistrict('')
      return
    }
    setLoadingDistricts(true)
    setSelectedDistrict('')
    getMapsDistricts(selectedState)
      .then((data) => setDistricts(data.districts ?? []))
      .catch(() => setDistricts([]))
      .finally(() => setLoadingDistricts(false))
  }, [selectedState])

  // ── Run search ─────────────────────────────────────────────────
  const search = useCallback(async (category) => {
    if (!category || !selectedState) return
    setIsLoading(true)
    setError(null)
    try {
      const data = await generateMapsLeads({
        category,
        state:        selectedState,
        district:     selectedDistrict || null,
        target,
        exclude_seen: excludeSeen,
      })
      setBusinesses(data.businesses ?? [])
      setStats(data.stats ?? null)
      setPipelineStats(data.pipeline_stats ?? null)
    } catch (err) {
      setError(err.message ?? 'Something went wrong. Please try again.')
      setBusinesses([])
      setStats(null)
      setPipelineStats(null)
    } finally {
      setIsLoading(false)
    }
  }, [selectedState, selectedDistrict, target, excludeSeen])

  // ── Clear results ──────────────────────────────────────────────
  const clear = useCallback(() => {
    setBusinesses([])
    setStats(null)
    setPipelineStats(null)
    setError(null)
  }, [])

  return {
    // geography
    states, districts, loadingStates, loadingDistricts,
    // selections
    selectedState, setSelectedState,
    selectedDistrict, setSelectedDistrict,
    target, setTarget,
    excludeSeen, setExcludeSeen,
    // results
    businesses, stats, pipelineStats, isLoading, error,
    // actions
    search, clear,
  }
}
