import { describe, expect, it } from 'vitest'
import { easeInOutCubic, easeOutCubic, Tweens } from './animate'

describe('easing', () => {
  it('starts at 0 and ends at 1', () => {
    for (const ease of [easeInOutCubic, easeOutCubic]) {
      expect(ease(0)).toBe(0)
      expect(ease(1)).toBe(1)
    }
    expect(easeInOutCubic(0.5)).toBeCloseTo(0.5)
  })
})

describe('Tweens', () => {
  it('steps from 0 to 1 over the duration and then resolves', async () => {
    const t = new Tweens()
    const seen: number[] = []
    t.update(1000)
    const done = t.run('a', 100, (k) => seen.push(k), (x) => x)
    t.update(1050)
    t.update(1100)
    await done
    expect(seen[0]).toBeCloseTo(0.5)
    expect(seen.at(-1)).toBe(1)
    expect(t.has('a')).toBe(false)
  })

  it('a new tween with the same name replaces the old one', async () => {
    const t = new Tweens()
    const first: number[] = []
    const second: number[] = []
    t.update(0)
    const a = t.run('x', 100, (k) => first.push(k))
    t.run('x', 100, (k) => second.push(k))
    await a // the replaced tween resolves right away
    t.update(200)
    expect(first).toEqual([])
    expect(second.at(-1)).toBe(1)
  })

  it('reduced motion jumps straight to the end', async () => {
    const t = new Tweens()
    t.reduced = true
    const seen: number[] = []
    await t.run('y', 500, (k) => seen.push(k))
    expect(seen).toEqual([1])
  })
})
