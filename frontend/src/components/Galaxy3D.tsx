import { useEffect, useImperativeHandle, useRef, type ReactNode, type Ref } from 'react'
import { GalaxyScene } from '../galaxy/scene'
import type { Galaxy, GalaxyNode } from '../types'

export interface Galaxy3DHandle {
  resetView(): void
  screenshot(): string | null
}

interface Props {
  ref?: Ref<Galaxy3DHandle>
  galaxy: Galaxy | null
  transition: 'build' | 'update'
  selected: string | null
  focusCluster: number | null
  rotate: boolean
  showLinks: boolean
  onSelect: (node: GalaxyNode | null) => void
  children?: ReactNode
}

/** React shell around GalaxyScene, which does the actual three.js work. */
export function Galaxy3D(props: Props) {
  const { ref, galaxy, transition, selected, focusCluster, rotate, showLinks, onSelect } = props
  const host = useRef<HTMLDivElement>(null)
  const scene = useRef<GalaxyScene | null>(null)
  const onSelectRef = useRef(onSelect)

  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    const s = new GalaxyScene(host.current!, { onSelect: (n) => onSelectRef.current(n) })
    scene.current = s
    return () => {
      s.dispose()
      scene.current = null
    }
  }, [])

  // App always sets galaxy and transition together
  useEffect(() => {
    if (galaxy) scene.current?.setData(galaxy, transition)
  }, [galaxy, transition])

  useEffect(() => {
    const s = scene.current
    if (!s || !galaxy) return
    if (selected) s.select(selected)
    else if (focusCluster !== null) s.focusOn(focusCluster)
    else s.select(null)
  }, [selected, focusCluster, galaxy])

  useEffect(() => scene.current?.setRotate(rotate), [rotate])
  useEffect(() => scene.current?.setLinksVisible(showLinks), [showLinks])

  useImperativeHandle(ref, () => ({
    resetView: () => void scene.current?.resetView(),
    screenshot: () => scene.current?.screenshot() ?? null,
  }), [])

  return (
    <div className="stage" ref={host}>
      {props.children}
    </div>
  )
}
