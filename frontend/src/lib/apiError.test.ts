import { afterEach, describe, expect, it, vi } from 'vitest'
import { ApiError, apiError, describeValidationDetail, fetchTemplates } from './api'

function json(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', ...headers } })
}

describe('apiError', () => {
  it('keeps the engine’s missing-input list', async () => {
    const err = await apiError(json(422, { detail: 'Missing or invalid required inputs: purchasePrice', missing: ['purchasePrice'] }))
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(422)
    expect(err.missing).toEqual(['purchasePrice'])
    expect(err.message).toContain('purchasePrice')
  })

  it('turns FastAPI validation arrays into words instead of "422 Unprocessable Entity"', async () => {
    const err = await apiError(
      json(422, { detail: [{ loc: ['body', 'values', 'holdPeriodYears'], msg: 'Input should be a valid number', type: 'x' }] }),
    )
    expect(err.message).toBe("Some values weren't accepted — values → holdPeriodYears: Input should be a valid number")
    expect(describeValidationDetail(Array.from({ length: 6 }, () => ({ msg: 'bad' })))).toContain('(and 2 more)')
  })

  it('explains a 500 without leaking internals and carries the request id', async () => {
    const err = await apiError(new Response('Internal Server Error', { status: 500, headers: { 'X-Request-ID': 'abc123' } }))
    expect(err.message).toContain('unexpected error (500)')
    expect(err.message).toContain('abc123')
    expect(err.requestId).toBe('abc123')
  })
})

describe('unreachable server', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('explains a connection failure instead of "Failed to fetch"', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')))
    const err = await fetchTemplates().catch((e: unknown) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect((err as ApiError).status).toBe(0)
    expect((err as ApiError).message).toContain("Can't reach the API server")
  })
})
