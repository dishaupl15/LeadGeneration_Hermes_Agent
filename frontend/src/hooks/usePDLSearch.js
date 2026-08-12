/**
 * usePDLSearch
 *
 * Hook for searching People Data Labs contacts for a single company.
 * Keeps loading / error / result state isolated from the main leads flow.
 *
 * Usage:
 *   const { search, result, isLoading, error, clear } = usePDLSearch()
 *   await search({ company_name: 'Getwell Hospital', domain: 'getwellhospitals.com' })
 */

import { useState, useCallback } from 'react'
import { searchPDLContacts } from '../services/api'

export function usePDLSearch() {
  const [result, setResult]     = useState(null)   // PeopleDataLabsResult | null
  const [isLoading, setLoading] = useState(false)
  const [error, setError]       = useState(null)   // string | null

  const search = useCallback(async ({ company_name, domain, website }) => {
    setLoading(true)
    setError(null)
    setResult(null)
    try {
      const data = await searchPDLContacts({ company_name, domain, website })
      setResult(data)
    } catch (err) {
      setError(err.message ?? 'PDL search failed.')
    } finally {
      setLoading(false)
    }
  }, [])

  const clear = useCallback(() => {
    setResult(null)
    setError(null)
  }, [])

  return { search, result, isLoading, error, clear }
}
