import { Minus, Plus } from 'lucide-react'
import { useEffect, useRef, useState, type PointerEvent, type WheelEvent } from 'react'

import { Modal } from '@/components/Modal'
import { Button } from '@/components/ui'

const VIEW = 280 // crop window, CSS px
const OUT = 256 // saved photo, px square
const MAX_ZOOM = 4

interface Loaded {
  img: HTMLImageElement
  url: string
  /** Scale at zoom 1: the shorter side just fills the window. */
  base: number
}

/** Keep the image covering the whole window at this scale. */
function clamp(x: number, y: number, w: number, h: number, scale: number) {
  return {
    x: Math.min(0, Math.max(VIEW - w * scale, x)),
    y: Math.min(0, Math.max(VIEW - h * scale, y)),
  }
}

/**
 * Square crop with a round preview: drag to position, zoom with the slider, buttons or
 * mouse wheel. Saves a 256 px image (PNG for PNG/GIF sources, which may be transparent;
 * JPEG otherwise), so uploads stay small whatever the camera made.
 */
export function AvatarCropDialog({
  file,
  saving,
  onCancel,
  onSave,
}: {
  file: File | null
  saving: boolean
  onCancel: () => void
  onSave: (photo: Blob) => void
}) {
  const [loaded, setLoaded] = useState<Loaded | null>(null)
  const [failed, setFailed] = useState(false)
  const [zoom, setZoom] = useState(1)
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const drag = useRef<{ id: number; x: number; y: number; px: number; py: number } | null>(null)

  useEffect(() => {
    setLoaded(null)
    setFailed(false)
    setZoom(1)
    if (!file) return
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const base = VIEW / Math.min(img.naturalWidth, img.naturalHeight)
      setLoaded({ img, url, base })
      setPos({
        x: (VIEW - img.naturalWidth * base) / 2,
        y: (VIEW - img.naturalHeight * base) / 2,
      })
    }
    img.onerror = () => {
      setFailed(true)
    }
    img.src = url
    return () => {
      URL.revokeObjectURL(url)
    }
  }, [file])

  const w = loaded?.img.naturalWidth ?? 1
  const h = loaded?.img.naturalHeight ?? 1
  const scale = (loaded?.base ?? 1) * zoom

  /** Zoom around the window's centre, so the face stays put. */
  function zoomTo(next: number) {
    if (!loaded) return
    const z = Math.min(MAX_ZOOM, Math.max(1, next))
    const s2 = loaded.base * z
    const cx = (VIEW / 2 - pos.x) / scale
    const cy = (VIEW / 2 - pos.y) / scale
    setZoom(z)
    setPos(clamp(VIEW / 2 - cx * s2, VIEW / 2 - cy * s2, w, h, s2))
  }

  function onPointerDown(e: PointerEvent<HTMLDivElement>) {
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { id: e.pointerId, x: e.clientX, y: e.clientY, px: pos.x, py: pos.y }
  }
  function onPointerMove(e: PointerEvent<HTMLDivElement>) {
    const d = drag.current
    if (d?.id !== e.pointerId) return
    setPos(clamp(d.px + e.clientX - d.x, d.py + e.clientY - d.y, w, h, scale))
  }
  function onPointerUp() {
    drag.current = null
  }
  function onWheel(e: WheelEvent<HTMLDivElement>) {
    zoomTo(zoom * (e.deltaY < 0 ? 1.08 : 1 / 1.08))
  }

  function save() {
    if (!loaded || !file) return
    const canvas = document.createElement('canvas')
    canvas.width = OUT
    canvas.height = OUT
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const keepAlpha = file.type === 'image/png' || file.type === 'image/gif'
    if (!keepAlpha) {
      ctx.fillStyle = '#ffffff'
      ctx.fillRect(0, 0, OUT, OUT)
    }
    ctx.imageSmoothingQuality = 'high'
    const side = VIEW / scale
    ctx.drawImage(loaded.img, -pos.x / scale, -pos.y / scale, side, side, 0, 0, OUT, OUT)
    canvas.toBlob(
      (blob) => {
        if (blob) onSave(blob)
      },
      keepAlpha ? 'image/png' : 'image/jpeg',
      0.9,
    )
  }

  return (
    <Modal
      open={file !== null}
      onOpenChange={(open) => {
        if (!open && !saving) onCancel()
      }}
      title="Crop your photo"
      description="Drag to position it. Zoom with the slider or your mouse wheel."
    >
      <div className="flex flex-col items-center">
        <div
          role="img"
          aria-label="Photo crop area"
          className="relative touch-none select-none overflow-hidden rounded-card bg-canvas"
          style={{ width: VIEW, height: VIEW, cursor: loaded ? 'grab' : 'default' }}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerCancel={onPointerUp}
          onWheel={onWheel}
        >
          {loaded && (
            <img
              src={loaded.url}
              alt=""
              draggable={false}
              className="pointer-events-none absolute left-0 top-0 max-w-none origin-top-left"
              style={{
                width: w,
                height: h,
                transform: `translate(${pos.x}px, ${pos.y}px) scale(${scale})`,
              }}
            />
          )}
          {/* Round window: everything outside the circle is dimmed. */}
          <div className="pointer-events-none absolute inset-0 rounded-full shadow-[0_0_0_999px_rgb(0_0_0/0.55)] ring-2 ring-white/80" />
          {!loaded && (
            <p className="absolute inset-0 flex items-center justify-center px-6 text-center text-sm text-fg-muted">
              {failed ? 'This file could not be read as an image.' : 'Loading…'}
            </p>
          )}
        </div>

        <div className="mt-5 flex w-full max-w-[280px] items-center gap-2">
          <button
            type="button"
            aria-label="Zoom out"
            onClick={() => {
              zoomTo(zoom / 1.25)
            }}
            className="rounded-control p-1.5 text-fg-muted hover:bg-canvas hover:text-fg"
          >
            <Minus className="size-4" />
          </button>
          <input
            type="range"
            aria-label="Zoom"
            min={1}
            max={MAX_ZOOM}
            step={0.01}
            value={zoom}
            disabled={!loaded}
            onChange={(e) => {
              zoomTo(Number(e.target.value))
            }}
            className="flex-1 accent-[rgb(var(--accent))]"
          />
          <button
            type="button"
            aria-label="Zoom in"
            onClick={() => {
              zoomTo(zoom * 1.25)
            }}
            className="rounded-control p-1.5 text-fg-muted hover:bg-canvas hover:text-fg"
          >
            <Plus className="size-4" />
          </button>
        </div>

        <div className="mt-5 flex w-full justify-end gap-2">
          <Button variant="ghost" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
          <Button variant="primary" onClick={save} loading={saving} disabled={!loaded}>
            Save photo
          </Button>
        </div>
      </div>
    </Modal>
  )
}
