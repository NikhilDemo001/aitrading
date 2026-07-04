import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import './Modal.css'

// Centered overlay dialog. Closes on Esc, backdrop click, or the ✕ button.
// Focus moves to the dialog on open and back to the previously focused element on close.
export function Modal({
  title,
  onClose,
  children,
  className = '',
}: {
  title?: ReactNode
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  const dialogRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const previouslyFocused = document.activeElement as HTMLElement | null
    dialogRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        // Swallow the event: the app's global hotkeys bind Escape to "square off all
        // positions" — closing a dialog must never reach that handler.
        e.stopPropagation()
        e.stopImmediatePropagation()
        onClose()
      }
    }
    // Capture phase so this runs before any bubble-phase global hotkey listener.
    document.addEventListener('keydown', onKey, true)
    // Freeze the page behind the overlay so scroll happens inside the dialog.
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey, true)
      document.body.style.overflow = prevOverflow
      previouslyFocused?.focus?.()
    }
  }, [onClose])

  return createPortal(
    <div className="mq-modal-backdrop" onClick={onClose}>
      <div
        ref={dialogRef}
        className={`mq-modal ${className}`}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        onClick={(e) => e.stopPropagation()}
      >
        <header className="mq-modal-hdr">
          <h3>{title}</h3>
          <button type="button" className="mq-modal-close" aria-label="Close" onClick={onClose}>
            ✕
          </button>
        </header>
        <div className="mq-modal-body">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
