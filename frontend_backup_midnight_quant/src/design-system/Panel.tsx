import type { ReactNode } from 'react'
import './Panel.css'

export function Panel({
  children,
  title,
  icon,
  actions,
  className = '',
  padded = true,
}: {
  children: ReactNode
  title?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  className?: string
  padded?: boolean
}) {
  return (
    <section className={`mq-panel ${className}`}>
      {(title || actions) && (
        <header className="mq-panel-hdr">
          <h3>
            {icon && <span className="mq-panel-icon">{icon}</span>}
            {title}
          </h3>
          {actions && <div className="mq-panel-actions">{actions}</div>}
        </header>
      )}
      <div className={padded ? 'mq-panel-body' : 'mq-panel-body mq-panel-body-flush'}>
        {children}
      </div>
    </section>
  )
}
