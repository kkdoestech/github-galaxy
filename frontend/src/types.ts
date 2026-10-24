export type Signal = 'collab' | 'follow'
export type LinkKind = 'mutual' | 'follow' | 'collab'

export interface RepoRef {
  name: string
  stars: number
  lang: string | null
}

export interface GalaxyNode {
  id: string
  name: string | null
  avatar: string | null
  bio: string | null
  followers: number
  hop: number
  cluster: number
  pos: [number, number, number]
  langs: string[]
  repos: RepoRef[]
}

/** One undirected edge. For one-way follows, source follows target. */
export interface GalaxyLink {
  source: string
  target: string
  w: number
  kind: LinkKind
}

export interface Cluster {
  id: number
  size: number
  label: string
  color: string
  top_langs: string[]
  top_members: string[]
  top_repos: string[]
}

export interface Galaxy {
  version: number
  key: string
  seed: string
  params: { depth: number; max: number; signal: Signal; k: number | null }
  built_at: string
  stats: { people: number; links: number; api_points: number; dropped: number }
  nodes: GalaxyNode[]
  links: GalaxyLink[]
  clusters: Cluster[]
  spectral: { k: number; k_auto: number; eigenvalues: number[]; modularity: number }
}

export interface Progress {
  stage: string
  done: number
  total: number
  msg: string
}

export interface ApiError {
  code: string
  msg: string
  reset_at: string | null
}

export interface BuildParams {
  login: string
  depth: number
  max: number
  signal: Signal
  k: number | null
}
