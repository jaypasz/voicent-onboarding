import type { CSSProperties } from 'react'
import type { Brand } from '../api/types'

// The server checks brand fields too; these checks are here because a brand ends up in a page in front of clients.
const HEX = /^#[0-9a-f]{6}$/i
const HTTPS_IMAGE = /^https:\/\/[^\s"'<>()]+$/

function channel(v: number): number {
  const c = v / 255
  return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
}

function luminance(hex: string): number {
  const n = parseInt(hex.slice(1), 16)
  return 0.2126 * channel((n >> 16) & 255) + 0.7152 * channel((n >> 8) & 255) + 0.0722 * channel(n & 255)
}

const contrast = (a: number, b: number) => (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)

/** White or near-black, whichever reads better on this colour. */
export function textOn(hex: string): string {
  const l = luminance(hex)
  return contrast(l, 1) >= contrast(l, luminance('#0b0b0b')) ? '#ffffff' : '#0b0b0b'
}

/** CSS variables for an element, so a brand colours only what is inside it (the client preview stays inside the admin app). */
export function brandStyle(brand?: Brand | null): CSSProperties {
  const c = brand?.primary_color
  if (!c || !HEX.test(c)) return {}
  return { '--accent': c, '--accent-text': textOn(c) } as CSSProperties
}

export function safeLogo(url?: string | null): string | null {
  return url && HTTPS_IMAGE.test(url) && url.length <= 500 ? url : null
}
