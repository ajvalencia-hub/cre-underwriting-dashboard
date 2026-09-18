import { useCallback, useRef, useState } from 'react'
import { ApiError, computeNative, type ComputeResponse } from './api'
import { stampResult, type ResultStamp } from './resultFreshness'

export interface NativeResult {
  response: ComputeResponse
  stamp: ResultStamp
}

export interface ExcelResult {
  outputs: Record<string, unknown>
  stamp: ResultStamp
}

export interface ComputeFailure {
  message: string
  missing: string[]
  at: number
}

/**
 * The deal's computed results (built-in engine and Excel read-back), each
 * stamped with the deal and inputs it came from. Responses for a deal that
 * is no longer active, or superseded by a newer request, are dropped — so a
 * slow compute can never paint another deal's (or older inputs') numbers.
 */
export function useComputeResults(activeDealIdRef: { current: string | null }) {
  const [native, setNative] = useState<NativeResult | null>(null)
  const [excel, setExcel] = useState<ExcelResult | null>(null)
  const [computing, setComputing] = useState(false)
  const [failure, setFailure] = useState<ComputeFailure | null>(null)
  const requestRef = useRef(0)

  const compute = useCallback(
    async (values: Record<string, unknown>) => {
      const id = ++requestRef.current
      const dealId = activeDealIdRef.current
      setComputing(true)
      setFailure(null)
      try {
        const response = await computeNative(values, { detail: true })
        if (id !== requestRef.current || dealId !== activeDealIdRef.current) return
        setNative({ response, stamp: stampResult('native', values, dealId) })
      } catch (err) {
        if (id !== requestRef.current || dealId !== activeDealIdRef.current) return
        setFailure({
          message: err instanceof Error ? err.message : 'Compute failed',
          missing: err instanceof ApiError ? err.missing : [],
          at: Date.now(),
        })
      } finally {
        if (id === requestRef.current) setComputing(false)
      }
    },
    [activeDealIdRef],
  )

  /** Template read-back from a Generate run started with `values` on `dealId`. */
  const recordExcel = useCallback(
    (outputs: Record<string, unknown>, values: Record<string, unknown>, dealId: string | null) => {
      if (dealId !== activeDealIdRef.current || Object.keys(outputs).length === 0) return
      setExcel({ outputs, stamp: stampResult('excel', values, dealId) })
    },
    [activeDealIdRef],
  )

  /** Deal switched / loaded: nothing on screen belongs to the new deal. */
  const reset = useCallback(() => {
    requestRef.current++
    setNative(null)
    setExcel(null)
    setFailure(null)
    setComputing(false)
  }, [])

  return { native, excel, computing, failure, compute, recordExcel, reset }
}
