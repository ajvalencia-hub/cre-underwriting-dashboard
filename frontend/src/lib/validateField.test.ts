import { describe, expect, it } from 'vitest'
import type { InputField } from '../types/schema'
import { validateField } from './validateField'

const field = (partial: Partial<InputField>): InputField => ({ id: 'f', label: 'F', type: 'number', ...partial }) as InputField

describe('validateField', () => {
  it('states bounds in the units the user types', () => {
    expect(validateField(field({ type: 'percent', max: 0.25 }), 0.3)).toBe('Max 25%')
    expect(validateField(field({ type: 'currency', min: 1000 }), 5)).toBe('Min $1,000')
    expect(validateField(field({ type: 'number', max: 50 }), 60)).toBe('Max 50')
  })

  it('flags required fields', () => {
    expect(validateField(field({ required: true }), '')).toBe('Required')
    expect(validateField(field({ required: true }), 3)).toBeNull()
  })
})
