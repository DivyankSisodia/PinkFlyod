import type { ReactNode } from "react"

const icons = {
  brand: <path d="m13 2-8 12h6l-1 8 9-12h-6l1-8Z" fill="currentColor" stroke="none" />,
  add: <path d="M12 5v14M5 12h14" />,
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />,
  recent: <><circle cx="12" cy="12" r="8.5" /><path d="M12 7.5v5l3 2" /></>,
  game: <><path d="M7.5 7h9c2 0 3.6 1.5 4 3.5l1 5.1a2.5 2.5 0 0 1-4.2 2.2l-2.2-2H8.9l-2.2 2a2.5 2.5 0 0 1-4.2-2.2l1-5.1A4.1 4.1 0 0 1 7.5 7Z" /><path d="M8 9.5v4m-2-2h4m5-.5h.01m2.5 2h.01" /></>,
  youtube: <><rect x="2.5" y="5.5" width="19" height="13" rx="4" fill="currentColor" stroke="none" /><path d="m10 9 5 3-5 3Z" fill="#31191e" stroke="none" /></>,
  instagram: <><rect x="4" y="4" width="16" height="16" rx="5" /><circle cx="12" cy="12" r="3.5" /><path d="M16.5 7.7h.01" /></>,
  link: <><path d="m10 13.5 4-4M8.5 15l-1 1a3.2 3.2 0 0 1-4.5-4.5l3.5-3.5a3.2 3.2 0 0 1 4.5 0m2 0 1-1a3.2 3.2 0 0 1 4.5 4.5L15 15a3.2 3.2 0 0 1-4.5 0" transform="translate(1 1)" /></>,
  arrow: <path d="M4 12h15m-6-6 6 6-6 6" />,
  chevron: <path d="m9 6 6 6-6 6" />,
  shield: <><path d="M12 3 5 6v5c0 4.5 2.8 7.9 7 10 4.2-2.1 7-5.5 7-10V6Z" /><path d="m9.5 12 1.6 1.6 3.5-3.5" /></>,
  portrait: <rect x="7" y="3.5" width="10" height="17" rx="2" />,
  split: <><rect x="5" y="4" width="14" height="16" rx="2" /><path d="M5 12h14" /></>,
  pip: <><rect x="5" y="4" width="14" height="16" rx="2" /><rect x="8" y="7" width="8" height="5" rx=".75" /></>,
  check: <path d="m5 12 4 4L19 6" />,
  settings: <><path d="M5 6h14M5 12h14M5 18h14" /><path d="M9 4v4m6 2v4m-5 2v4" strokeWidth="2.5" /></>,
  activity: <path d="M3 12h4l3-7 4 14 3-7h4" />,
} satisfies Record<string, ReactNode>

export function WorkspaceIcon({ name, size = 20 }: { name: keyof typeof icons; size?: number }) {
  return (
    <svg aria-hidden="true" width={size} height={size} viewBox="0 0 24 24" fill="none"
      stroke="currentColor" strokeWidth="1.65" strokeLinecap="round" strokeLinejoin="round">
      {icons[name]}
    </svg>
  )
}
