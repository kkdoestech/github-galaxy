export type Ease = (t: number) => number

export const easeInOutCubic: Ease = (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2)
export const easeOutCubic: Ease = (t) => 1 - (1 - t) ** 3

interface Tween {
  start: number
  duration: number
  ease: Ease
  step: (k: number) => void
  resolve: () => void
}

/**
 * Named tweens driven by the scene's render loop. Starting a tween with a name that is
 * already running replaces it, so a new selection fade simply takes over from the old one.
 */
export class Tweens {
  reduced = false
  private items = new Map<string, Tween>()
  private now = -1 // time of the last frame; -1 before the first one

  run(name: string, duration: number, step: (k: number) => void, ease: Ease = easeInOutCubic) {
    return new Promise<void>((resolve) => {
      this.items.get(name)?.resolve()
      if (this.reduced || duration <= 0) {
        this.items.delete(name)
        step(1)
        resolve()
        return
      }
      const start = this.now >= 0 ? this.now : performance.now()
      this.items.set(name, { start, duration, ease, step, resolve })
    })
  }

  has(name: string) {
    return this.items.has(name)
  }

  update(now: number) {
    this.now = now
    for (const [name, t] of this.items) {
      const raw = Math.min(1, Math.max(0, (now - t.start) / t.duration))
      t.step(t.ease(raw))
      if (raw >= 1) {
        this.items.delete(name)
        t.resolve()
      }
    }
  }
}
