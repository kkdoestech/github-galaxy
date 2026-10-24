import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import type { Galaxy, GalaxyNode } from '../types'
import { easeInOutCubic, easeOutCubic, Tweens } from './animate'

const BG = '#0D1017' // ayu ui.bg
const ACCENT = '#E6B450'
const SELECT = '#BFBDB6'
const IDLE_MS = 5000
const DIM = 0.14
const LINK_ALPHA = 0.16
const LINK_ALPHA_FOCUSED = 0.035
const MAX_PARTICLE_LINKS = 160
const PARTICLE_SPEED = 70 // world units per second

export interface SceneCallbacks {
  onSelect: (node: GalaxyNode | null) => void
}

export function starSize(followers: number) {
  return 3.5 + 2.6 * Math.log10(1 + followers)
}

const RING = 1.7 // ring diameter as a multiple of the star's

/** "#RRGGBB" -> sRGB floats, the values the star shader writes out as is. */
function hexToRgb(hex: string): [number, number, number] {
  const v = parseInt(hex.slice(1), 16)
  return [((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255]
}

const toLinear = (c: number) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)

const STAR_VERT = /* glsl */ `
  attribute float size;
  attribute float alpha;
  attribute vec3 starColor;
  uniform float scale;
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    vColor = starColor;
    vAlpha = alpha;
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * scale / -mv.z;
    gl_Position = projectionMatrix * mv;
  }`

const STAR_FRAG = /* glsl */ `
  varying vec3 vColor;
  varying float vAlpha;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5) discard;
    float edge = 1.0 - smoothstep(0.44, 0.5, d);
    gl_FragColor = vec4(vColor, vAlpha * edge);
  }`

const MARK_VERT = /* glsl */ `
  uniform float size;
  uniform float scale;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_PointSize = size * scale / -mv.z;
    gl_Position = projectionMatrix * mv;
  }`

// inner = 0.0 draws a filled dot, anything else a ring
const MARK_FRAG = /* glsl */ `
  uniform vec3 color;
  uniform float opacity;
  uniform float inner;
  void main() {
    float d = length(gl_PointCoord - 0.5);
    if (d > 0.5 || d < inner) discard;
    gl_FragColor = vec4(color, opacity);
  }`

function markMaterial(hex: string, size: number, inner: number) {
  const [r, g, b] = hexToRgb(hex)
  return new THREE.ShaderMaterial({
    uniforms: {
      size: { value: size },
      scale: { value: 1 },
      color: { value: new THREE.Vector3(r, g, b) },
      opacity: { value: 1 },
      inner: { value: inner },
    },
    vertexShader: MARK_VERT,
    fragmentShader: MARK_FRAG,
    transparent: true,
    depthWrite: false,
  })
}

interface Particle {
  a: number
  b: number
  offset: number
}

export class GalaxyScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera: THREE.PerspectiveCamera
  private controls: OrbitControls
  private tweens = new Tweens()
  private raf = 0
  private resizeObserver: ResizeObserver
  private motionQuery: MediaQueryList

  private galaxy: Galaxy | null = null
  private nodes: GalaxyNode[] = []
  private index = new Map<string, number>()
  private pos = new Float32Array(0)
  private target = new Float32Array(0)
  private color = new Float32Array(0)
  private alpha = new Float32Array(0)
  private size = new Float32Array(0)
  private baseSize = new Float32Array(0)
  private linkEnds = new Uint32Array(0)
  private linkKinds: string[] = []
  private nodeLinks: number[][] = []
  private centers: THREE.Vector3[] = []
  private radii: number[] = []
  private seedIndex = -1
  private home = { target: new THREE.Vector3(), distance: 600 }

  private starGeom = new THREE.BufferGeometry()
  private starMat: THREE.ShaderMaterial
  private stars: THREE.Points
  private linkGeom = new THREE.BufferGeometry()
  private linkMat: THREE.LineBasicMaterial
  private links: THREE.LineSegments
  private highlightGeom = new THREE.BufferGeometry()
  private highlightMat: THREE.LineBasicMaterial
  private highlight: THREE.LineSegments
  private highlightLinks: number[] = []
  private particleGeom = new THREE.BufferGeometry()
  private particleMat: THREE.ShaderMaterial
  private particles: THREE.Points
  private particleList: Particle[] = []
  private seedRing: THREE.Points
  private selectRing: THREE.Points

  private selected = -1
  private focusCluster = -1
  private hovered = -1
  private grown = new Set<number>()
  private down: { x: number; y: number; index: number } | null = null
  private dragging = false
  private lastInteraction = 0
  private rotateEnabled = true
  private linksVisible = true
  private reducedMotion = false

  private tooltip: HTMLDivElement
  private seedLabel: HTMLDivElement
  private selectLabel: HTMLDivElement
  private container: HTMLElement
  private cb: SceneCallbacks

  constructor(container: HTMLElement, cb: SceneCallbacks) {
    this.container = container
    this.cb = cb

    this.renderer = new THREE.WebGLRenderer({ antialias: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    this.renderer.setClearColor(BG)
    this.renderer.domElement.className = 'galaxy-canvas'
    container.appendChild(this.renderer.domElement)

    this.camera = new THREE.PerspectiveCamera(50, 1, 1, 60000)
    this.camera.position.set(0, 200, 600)
    this.controls = new OrbitControls(this.camera, this.renderer.domElement)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.08
    this.controls.rotateSpeed = 0.6
    this.controls.zoomSpeed = 0.9
    this.controls.autoRotateSpeed = 0.35
    this.controls.minDistance = 15
    this.controls.maxDistance = 30000

    this.starMat = new THREE.ShaderMaterial({
      uniforms: { scale: { value: 1 } },
      vertexShader: STAR_VERT,
      fragmentShader: STAR_FRAG,
      transparent: true,
      depthWrite: false,
    })
    this.stars = new THREE.Points(this.starGeom, this.starMat)
    this.linkMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: LINK_ALPHA,
      depthWrite: false,
    })
    this.links = new THREE.LineSegments(this.linkGeom, this.linkMat)
    this.highlightMat = new THREE.LineBasicMaterial({
      color: ACCENT,
      transparent: true,
      opacity: 0,
      depthWrite: false,
    })
    this.highlight = new THREE.LineSegments(this.highlightGeom, this.highlightMat)
    this.particleMat = markMaterial(ACCENT, 3.2, 0)
    this.particles = new THREE.Points(this.particleGeom, this.particleMat)
    this.seedRing = new THREE.Points(this.markGeometry(), markMaterial(ACCENT, 10, 0.42))
    this.selectRing = new THREE.Points(this.markGeometry(), markMaterial(SELECT, 10, 0.42))
    this.selectRing.visible = false
    this.seedRing.visible = false

    const ordered = [this.links, this.highlight, this.stars, this.particles, this.seedRing,
      this.selectRing]
    ordered.forEach((obj, i) => {
      obj.frustumCulled = false
      obj.renderOrder = i
      this.scene.add(obj)
    })

    this.tooltip = this.makeLabel('galaxy-tooltip')
    this.seedLabel = this.makeLabel('galaxy-label galaxy-label-seed')
    this.selectLabel = this.makeLabel('galaxy-label')

    const el = this.renderer.domElement
    el.addEventListener('pointerdown', this.onPointerDown, { capture: true })
    el.addEventListener('pointermove', this.onPointerMove)
    el.addEventListener('pointerup', this.onPointerUp)
    el.addEventListener('pointerleave', this.onPointerLeave)
    el.addEventListener('wheel', this.touch, { passive: true })

    this.motionQuery = window.matchMedia('(prefers-reduced-motion: reduce)')
    this.setReducedMotion(this.motionQuery.matches)
    this.motionQuery.addEventListener('change', this.onMotionChange)

    this.resizeObserver = new ResizeObserver(() => this.resize())
    this.resizeObserver.observe(container)
    this.resize()
    this.raf = requestAnimationFrame(this.loop)
  }

  // ---- public API --------------------------------------------------------------------

  /** Load a galaxy. 'build' spreads stars out from their cluster centers; 'update' glides. */
  setData(g: Galaxy, mode: 'build' | 'update') {
    const prev = { index: this.index, pos: this.pos, color: this.color }
    const reuse = mode === 'update' && prev.index.size > 0
    this.galaxy = g
    this.nodes = g.nodes
    const n = g.nodes.length
    this.index = new Map(g.nodes.map((node, i) => [node.id, i]))
    this.seedIndex = this.index.get(g.seed) ?? -1

    this.target = new Float32Array(n * 3)
    g.nodes.forEach((node, i) => this.target.set(node.pos, i * 3))
    this.computeClusters()

    const start = new Float32Array(n * 3)
    const colorFrom = new Float32Array(n * 3)
    const colorTo = new Float32Array(n * 3)
    const colorOf = new Map(g.clusters.map((c) => [c.id, hexToRgb(c.color)]))
    g.nodes.forEach((node, i) => {
      const rgb = colorOf.get(node.cluster) ?? [0.75, 0.74, 0.71]
      colorTo.set(rgb, i * 3)
      const old = reuse ? prev.index.get(node.id) : undefined
      if (old !== undefined) {
        start.set(prev.pos.subarray(old * 3, old * 3 + 3), i * 3)
        colorFrom.set(prev.color.subarray(old * 3, old * 3 + 3), i * 3)
      } else {
        const c = this.centers[node.cluster] ?? new THREE.Vector3()
        start[i * 3] = c.x + (Math.random() - 0.5) * 6
        start[i * 3 + 1] = c.y + (Math.random() - 0.5) * 6
        start[i * 3 + 2] = c.z + (Math.random() - 0.5) * 6
        colorFrom.set(rgb, i * 3)
      }
    })

    this.pos = start.slice()
    this.color = colorFrom.slice()
    this.alpha = new Float32Array(n).fill(1)
    this.baseSize = new Float32Array(n)
    g.nodes.forEach((node, i) => {
      this.baseSize[i] = starSize(node.followers) * (i === this.seedIndex ? 1.5 : 1)
    })
    this.size = this.baseSize.slice()

    this.starGeom.dispose()
    this.starGeom = new THREE.BufferGeometry()
    this.starGeom.setAttribute('position', new THREE.BufferAttribute(this.pos, 3))
    this.starGeom.setAttribute('starColor', new THREE.BufferAttribute(this.color, 3))
    this.starGeom.setAttribute('size', new THREE.BufferAttribute(this.size, 1))
    this.starGeom.setAttribute('alpha', new THREE.BufferAttribute(this.alpha, 1))
    this.stars.geometry = this.starGeom

    this.buildLinks(g)

    this.selected = -1
    this.focusCluster = -1
    this.hovered = -1
    this.grown.clear()
    this.highlightLinks = []
    this.particleList = []
    this.tooltip.style.display = 'none'
    this.applyFocus(false)

    const duration = mode === 'build' ? 1400 : 700
    void this.tweens.run('layout', duration, (k) => {
      for (let i = 0; i < start.length; i++) {
        this.pos[i] = start[i] + (this.target[i] - start[i]) * k
        this.color[i] = colorFrom[i] + (colorTo[i] - colorFrom[i]) * k
      }
      this.writeStars(true)
    }, easeOutCubic)
    void this.tweens.run('linkAlpha', duration, (k) => {
      this.linkMat.opacity = LINK_ALPHA * k
    })

    this.computeHome()
    if (mode === 'build') {
      const dir = new THREE.Vector3(0, 0.32, 1).normalize()
      const near = this.home.target.clone().add(dir.clone().multiplyScalar(this.home.distance * 0.3))
      this.camera.position.copy(near)
      this.controls.target.copy(this.home.target)
      void this.flyTo(this.home.target, this.home.distance, duration, true)
    }
    this.updateMarks()
  }

  /** Highlight one person and their links, fly to them. null clears. */
  select(id: string | null) {
    const i = id === null ? -1 : (this.index.get(id) ?? -1)
    this.selected = i
    this.focusCluster = -1
    this.applyFocus(true)
    if (i >= 0) void this.flyTo(this.nodePos(i), Math.max(200, this.baseSize[i] * 14))
  }

  /** Isolate a cluster and fly to it. null clears. */
  focusOn(cluster: number | null) {
    this.focusCluster = cluster ?? -1
    this.selected = -1
    this.applyFocus(true)
    if (cluster !== null && this.centers[cluster]) {
      void this.flyTo(this.centers[cluster], Math.max(120, this.radii[cluster] * 3.4))
    }
  }

  resetView() {
    return this.flyTo(this.home.target, this.home.distance)
  }

  setRotate(on: boolean) {
    this.rotateEnabled = on
  }

  setLinksVisible(on: boolean) {
    this.linksVisible = on
    this.links.visible = on
  }

  screenshot(): string {
    this.renderer.render(this.scene, this.camera)
    return this.renderer.domElement.toDataURL('image/png')
  }

  dispose() {
    cancelAnimationFrame(this.raf)
    this.resizeObserver.disconnect()
    this.motionQuery.removeEventListener('change', this.onMotionChange)
    const el = this.renderer.domElement
    el.removeEventListener('pointerdown', this.onPointerDown, { capture: true })
    el.removeEventListener('pointermove', this.onPointerMove)
    el.removeEventListener('pointerup', this.onPointerUp)
    el.removeEventListener('pointerleave', this.onPointerLeave)
    el.removeEventListener('wheel', this.touch)
    this.controls.dispose()
    for (const obj of [this.stars, this.links, this.highlight, this.particles, this.seedRing,
      this.selectRing]) {
      obj.geometry.dispose()
      ;(obj.material as THREE.Material).dispose()
    }
    this.renderer.dispose()
    el.remove()
    this.tooltip.remove()
    this.seedLabel.remove()
    this.selectLabel.remove()
  }

  // ---- data helpers ------------------------------------------------------------------

  private markGeometry() {
    const geom = new THREE.BufferGeometry()
    geom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(3), 3))
    return geom
  }

  private makeLabel(className: string) {
    const el = document.createElement('div')
    el.className = className
    el.style.display = 'none'
    this.container.appendChild(el)
    return el
  }

  private nodePos(i: number) {
    return new THREE.Vector3(this.target[i * 3], this.target[i * 3 + 1], this.target[i * 3 + 2])
  }

  private computeClusters() {
    const k = (this.galaxy?.clusters.length ?? 0) || 1
    const sums = Array.from({ length: k }, () => new THREE.Vector3())
    const counts = new Array(k).fill(0)
    this.nodes.forEach((node, i) => {
      sums[node.cluster]?.add(this.nodePos(i))
      counts[node.cluster] += 1
    })
    this.centers = sums.map((s, c) => s.divideScalar(Math.max(1, counts[c])))
    this.radii = new Array(k).fill(0)
    this.nodes.forEach((node, i) => {
      const d = this.nodePos(i).distanceTo(this.centers[node.cluster])
      this.radii[node.cluster] = Math.max(this.radii[node.cluster], d)
    })
  }

  private computeHome() {
    const n = this.nodes.length
    const center = new THREE.Vector3()
    for (let i = 0; i < n; i++) center.add(this.nodePos(i))
    if (n) center.divideScalar(n)
    // fit the bulk of the galaxy, not its farthest stray star
    const dists = Array.from({ length: n }, (_, i) => this.nodePos(i).distanceTo(center))
    dists.sort((a, b) => a - b)
    const radius = Math.max(50, (dists[Math.floor(n * 0.97)] ?? 0) * 1.08)
    const vfov = THREE.MathUtils.degToRad(this.camera.fov)
    const hfov = 2 * Math.atan(Math.tan(vfov / 2) * this.camera.aspect)
    this.home = { target: center, distance: radius / Math.sin(Math.min(vfov, hfov) / 2) }
  }

  private buildLinks(g: Galaxy) {
    const ends: number[] = []
    this.linkKinds = []
    this.nodeLinks = this.nodes.map(() => [])
    for (const link of g.links) {
      const a = this.index.get(link.source)
      const b = this.index.get(link.target)
      if (a === undefined || b === undefined) continue
      const j = ends.length / 2
      ends.push(a, b)
      this.linkKinds.push(link.kind)
      this.nodeLinks[a].push(j)
      this.nodeLinks[b].push(j)
    }
    this.linkEnds = Uint32Array.from(ends)
    const m = this.linkKinds.length
    this.linkGeom.dispose()
    this.linkGeom = new THREE.BufferGeometry()
    this.linkGeom.setAttribute('position', new THREE.BufferAttribute(new Float32Array(m * 6), 3))
    this.linkGeom.setAttribute('color', new THREE.BufferAttribute(new Float32Array(m * 6), 3))
    this.links.geometry = this.linkGeom
  }

  // ---- writing geometry --------------------------------------------------------------

  private writeStars(colorsToo = false) {
    const attrs = this.starGeom.attributes
    attrs.position.needsUpdate = true
    if (colorsToo) attrs.starColor.needsUpdate = true
    this.writeLinks(colorsToo)
    this.updateMarks()
  }

  private writeLinks(colorsToo: boolean) {
    const posAttr = this.linkGeom.attributes.position as THREE.BufferAttribute
    const out = posAttr.array as Float32Array
    const ends = this.linkEnds
    const p = this.pos
    for (let j = 0; j < ends.length; j++) {
      const s = ends[j] * 3
      out[j * 3] = p[s]
      out[j * 3 + 1] = p[s + 1]
      out[j * 3 + 2] = p[s + 2]
    }
    posAttr.needsUpdate = true
    if (colorsToo) {
      const colAttr = this.linkGeom.attributes.color as THREE.BufferAttribute
      const col = colAttr.array as Float32Array
      for (let j = 0; j < ends.length; j++) {
        const s = ends[j] * 3
        col[j * 3] = toLinear(this.color[s])
        col[j * 3 + 1] = toLinear(this.color[s + 1])
        col[j * 3 + 2] = toLinear(this.color[s + 2])
      }
      colAttr.needsUpdate = true
    }
    this.writeHighlight()
  }

  private writeHighlight() {
    const list = this.highlightLinks
    let attr = this.highlightGeom.attributes.position as THREE.BufferAttribute | undefined
    if (!attr || attr.count !== list.length * 2) {
      this.highlightGeom.dispose()
      this.highlightGeom = new THREE.BufferGeometry()
      attr = new THREE.BufferAttribute(new Float32Array(list.length * 6), 3)
      this.highlightGeom.setAttribute('position', attr)
      this.highlight.geometry = this.highlightGeom
    }
    const out = attr.array as Float32Array
    list.forEach((j, q) => {
      for (let e = 0; e < 2; e++) {
        const s = this.linkEnds[j * 2 + e] * 3
        out.set(this.pos.subarray(s, s + 3), q * 6 + e * 3)
      }
    })
    attr.needsUpdate = true
  }

  private updateMarks() {
    const place = (ring: THREE.Points, i: number) => {
      ring.visible = i >= 0
      if (i < 0) return
      const attr = ring.geometry.attributes.position as THREE.BufferAttribute
      attr.setXYZ(0, this.pos[i * 3], this.pos[i * 3 + 1], this.pos[i * 3 + 2])
      attr.needsUpdate = true
      ;(ring.material as THREE.ShaderMaterial).uniforms.size.value = this.baseSize[i] * RING
    }
    place(this.seedRing, this.seedIndex)
    place(this.selectRing, this.selected === this.seedIndex ? -1 : this.selected)
  }

  // ---- focus, hover, particles -------------------------------------------------------

  private applyFocus(animate: boolean) {
    const n = this.nodes.length
    const to = new Float32Array(n)
    let linkSet: number[] = []
    if (this.selected >= 0) {
      to.fill(DIM)
      to[this.selected] = 1
      linkSet = this.nodeLinks[this.selected]
      for (const j of linkSet) {
        to[this.linkEnds[j * 2]] = 1
        to[this.linkEnds[j * 2 + 1]] = 1
      }
      this.highlightMat.color.set(ACCENT)
    } else if (this.focusCluster >= 0) {
      const c = this.focusCluster
      this.nodes.forEach((node, i) => (to[i] = node.cluster === c ? 1 : DIM))
      for (let j = 0; j < this.linkKinds.length; j++) {
        const a = this.nodes[this.linkEnds[j * 2]]
        const b = this.nodes[this.linkEnds[j * 2 + 1]]
        if (a.cluster === c && b.cluster === c) linkSet.push(j)
      }
      this.highlightMat.color.set(this.galaxy?.clusters[c]?.color ?? ACCENT)
    } else {
      to.fill(1)
    }
    this.highlightLinks = linkSet
    this.writeHighlight()

    const focused = this.selected >= 0 || this.focusCluster >= 0
    const from = this.alpha.slice()
    const linkFrom = this.linkMat.opacity
    const linkTo = focused ? LINK_ALPHA_FOCUSED : LINK_ALPHA
    const hiFrom = this.highlightMat.opacity
    const hiTo = this.selected >= 0 ? 0.65 : this.focusCluster >= 0 ? 0.32 : 0
    void this.tweens.run('alpha', animate ? 300 : 0, (k) => {
      for (let i = 0; i < n; i++) this.alpha[i] = from[i] + (to[i] - from[i]) * k
      this.starGeom.attributes.alpha.needsUpdate = true
      if (!this.tweens.has('linkAlpha')) this.linkMat.opacity = linkFrom + (linkTo - linkFrom) * k
      this.highlightMat.opacity = hiFrom + (hiTo - hiFrom) * k
    })

    this.setupParticles()
    this.updateMarks()
    this.selectLabel.style.display = 'none'
  }

  private setupParticles() {
    this.particleList = []
    if (this.selected >= 0 && !this.reducedMotion) {
      const s = this.selected
      for (const j of this.nodeLinks[s].slice(0, MAX_PARTICLE_LINKS)) {
        const a = this.linkEnds[j * 2]
        const b = this.linkEnds[j * 2 + 1]
        const kind = this.linkKinds[j]
        if (kind === 'collab') continue
        this.particleList.push({ a, b, offset: Math.random() })
        if (kind === 'mutual') this.particleList.push({ a: b, b: a, offset: Math.random() })
      }
    }
    this.particleGeom.dispose()
    this.particleGeom = new THREE.BufferGeometry()
    this.particleGeom.setAttribute(
      'position',
      new THREE.BufferAttribute(new Float32Array(this.particleList.length * 3), 3),
    )
    this.particles.geometry = this.particleGeom
  }

  private updateParticles(now: number) {
    if (!this.particleList.length) return
    const attr = this.particleGeom.attributes.position as THREE.BufferAttribute
    const out = attr.array as Float32Array
    const p = this.pos
    this.particleList.forEach((pt, q) => {
      const a = pt.a * 3
      const b = pt.b * 3
      const dx = p[b] - p[a]
      const dy = p[b + 1] - p[a + 1]
      const dz = p[b + 2] - p[a + 2]
      const len = Math.max(1, Math.hypot(dx, dy, dz))
      const t = ((now / 1000) * (PARTICLE_SPEED / len) + pt.offset) % 1
      out[q * 3] = p[a] + dx * t
      out[q * 3 + 1] = p[a + 1] + dy * t
      out[q * 3 + 2] = p[a + 2] + dz * t
    })
    attr.needsUpdate = true
  }

  private setHovered(i: number) {
    if (i === this.hovered) return
    this.hovered = i
    if (i >= 0) this.grown.add(i)
    const from = new Map([...this.grown].map((j) => [j, this.size[j]]))
    void this.tweens.run('hover', 150, (k) => {
      for (const [j, s0] of from) {
        const goal = this.baseSize[j] * (j === this.hovered ? 1.5 : 1)
        this.size[j] = s0 + (goal - s0) * k
      }
      this.starGeom.attributes.size.needsUpdate = true
      if (k >= 1) for (const j of from.keys()) if (j !== this.hovered) this.grown.delete(j)
    })
    this.renderer.domElement.style.cursor = i >= 0 ? 'pointer' : ''
  }

  /** The front-most star under a screen point, in screen space (sprites are round). */
  private pick(clientX: number, clientY: number): number {
    const rect = this.renderer.domElement.getBoundingClientRect()
    const x = clientX - rect.left
    const y = clientY - rect.top
    const scale = rect.height / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2))
    const view = this.camera.matrixWorldInverse
    const proj = this.camera.projectionMatrix
    const v = new THREE.Vector3()
    let best = -1
    let bestDepth = Infinity
    for (let i = 0; i < this.nodes.length; i++) {
      v.set(this.pos[i * 3], this.pos[i * 3 + 1], this.pos[i * 3 + 2]).applyMatrix4(view)
      const depth = -v.z
      if (depth <= 1) continue
      v.applyMatrix4(proj)
      const sx = ((v.x + 1) / 2) * rect.width
      const sy = ((1 - v.y) / 2) * rect.height
      const r = Math.max((this.size[i] * scale) / depth / 2, 5)
      const dx = sx - x
      const dy = sy - y
      if (dx * dx + dy * dy <= r * r && depth < bestDepth) {
        best = i
        bestDepth = depth
      }
    }
    return best
  }

  // ---- camera ------------------------------------------------------------------------

  private flyTo(target: THREE.Vector3, distance: number, duration = 800, keepDirection = false) {
    const fromPos = this.camera.position.clone()
    const fromTarget = this.controls.target.clone()
    const dir = fromPos.clone().sub(fromTarget).normalize()
    if (!keepDirection && dir.lengthSq() === 0) dir.set(0, 0, 1)
    const toPos = target.clone().add(dir.multiplyScalar(distance))
    this.lastInteraction = performance.now()
    return this.tweens.run('camera', duration, (k) => {
      this.camera.position.lerpVectors(fromPos, toPos, k)
      this.controls.target.lerpVectors(fromTarget, target, k)
    }, easeInOutCubic)
  }

  // ---- events ------------------------------------------------------------------------

  private touch = () => {
    this.lastInteraction = performance.now()
    this.controls.autoRotate = false
  }

  private onPointerDown = (e: PointerEvent) => {
    this.touch()
    const index = this.pick(e.clientX, e.clientY)
    this.down = { x: e.clientX, y: e.clientY, index }
    this.dragging = false
    if (index >= 0) this.controls.enabled = false // dragging a star, not the view
  }

  private onPointerMove = (e: PointerEvent) => {
    if (this.down) {
      this.touch()
      const moved = Math.hypot(e.clientX - this.down.x, e.clientY - this.down.y)
      if (this.down.index >= 0 && (this.dragging || moved > 4)) {
        this.dragging = true
        this.dragStar(this.down.index, e)
      }
      return
    }
    const i = this.pick(e.clientX, e.clientY)
    this.setHovered(i)
    this.showTooltip(i, e)
  }

  private onPointerUp = (e: PointerEvent) => {
    const down = this.down
    this.down = null
    this.controls.enabled = true
    if (!down) return
    const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y)
    if (!this.dragging && moved <= 4) {
      this.cb.onSelect(down.index >= 0 ? this.nodes[down.index] : null)
    }
    this.dragging = false
  }

  private onPointerLeave = () => {
    this.setHovered(-1)
    this.tooltip.style.display = 'none'
  }

  private onMotionChange = (e: MediaQueryListEvent) => this.setReducedMotion(e.matches)

  private setReducedMotion(on: boolean) {
    this.reducedMotion = on
    this.tweens.reduced = on
    this.setupParticles()
  }

  private dragStar(i: number, e: PointerEvent) {
    const rect = this.renderer.domElement.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    )
    const ray = new THREE.Raycaster()
    ray.setFromCamera(ndc, this.camera)
    const normal = this.camera.getWorldDirection(new THREE.Vector3())
    const plane = new THREE.Plane().setFromNormalAndCoplanarPoint(normal, this.nodePos(i))
    const hit = ray.ray.intersectPlane(plane, new THREE.Vector3())
    if (!hit) return
    this.target.set([hit.x, hit.y, hit.z], i * 3)
    this.pos.set([hit.x, hit.y, hit.z], i * 3)
    this.writeStars()
    this.tooltip.style.display = 'none'
  }

  private showTooltip(i: number, e: PointerEvent) {
    if (i < 0) {
      this.tooltip.style.display = 'none'
      return
    }
    const node = this.nodes[i]
    const cluster = this.galaxy?.clusters[node.cluster]
    const rect = this.container.getBoundingClientRect()
    this.tooltip.textContent = ''
    const strong = document.createElement('strong')
    strong.textContent = node.id
    this.tooltip.append(strong)
    if (node.name && node.name !== node.id) this.tooltip.append(` (${node.name})`)
    if (cluster) {
      const line = document.createElement('div')
      line.className = 'galaxy-tooltip-sub'
      line.textContent = `Cluster ${cluster.id + 1}: ${cluster.label}`
      this.tooltip.append(line)
    }
    this.tooltip.style.display = 'block'
    const x = Math.min(e.clientX - rect.left + 14, rect.width - this.tooltip.offsetWidth - 4)
    this.tooltip.style.left = `${Math.max(4, x)}px`
    this.tooltip.style.top = `${e.clientY - rect.top + 14}px`
  }

  /** Keep a name tag just right of a star's ring. */
  private placeLabel(el: HTMLDivElement, i: number, text: string) {
    const v = i < 0 ? null
      : new THREE.Vector3(this.pos[i * 3], this.pos[i * 3 + 1], this.pos[i * 3 + 2])
        .applyMatrix4(this.camera.matrixWorldInverse)
    const depth = v ? -v.z : 0
    if (!v || depth <= 1) {
      el.style.display = 'none'
      return
    }
    v.applyMatrix4(this.camera.projectionMatrix)
    const w = this.container.clientWidth
    const h = this.container.clientHeight
    const scale = h / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2))
    const ring = (this.baseSize[i] * RING * scale) / depth / 2
    if (el.textContent !== text) el.textContent = text
    el.style.display = 'block'
    el.style.transform = `translate(${((v.x + 1) / 2) * w + ring + 4}px, ${((1 - v.y) / 2) * h - 9}px)`
  }

  // ---- frame loop --------------------------------------------------------------------

  private resize() {
    const w = Math.max(1, this.container.clientWidth)
    const h = Math.max(1, this.container.clientHeight)
    this.renderer.setSize(w, h, false)
    this.renderer.domElement.style.width = `${w}px`
    this.renderer.domElement.style.height = `${h}px`
    this.camera.aspect = w / h
    this.camera.updateProjectionMatrix()
    const buffer = this.renderer.getDrawingBufferSize(new THREE.Vector2())
    const scale = buffer.y / (2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2))
    this.starMat.uniforms.scale.value = scale
    for (const mark of [this.particles, this.seedRing, this.selectRing]) {
      ;(mark.material as THREE.ShaderMaterial).uniforms.scale.value = scale
    }
  }

  private loop = (now: number) => {
    this.raf = requestAnimationFrame(this.loop)
    this.tweens.update(now)
    this.controls.autoRotate =
      this.rotateEnabled &&
      !this.reducedMotion &&
      !this.down &&
      !this.tweens.has('camera') &&
      this.nodes.length > 0 &&
      now - this.lastInteraction > IDLE_MS
    this.controls.update()
    this.updateParticles(now)
    if (this.galaxy) {
      this.placeLabel(this.seedLabel, this.seedIndex, this.galaxy.seed)
      const sel = this.selected === this.seedIndex ? -1 : this.selected
      this.placeLabel(this.selectLabel, sel, sel >= 0 ? this.nodes[sel].id : '')
    }
    this.links.visible = this.linksVisible
    this.renderer.render(this.scene, this.camera)
  }
}
