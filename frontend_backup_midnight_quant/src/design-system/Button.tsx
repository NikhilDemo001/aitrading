import type { ButtonHTMLAttributes } from 'react'
import './Button.css'

type Variant = 'primary' | 'ghost' | 'danger' | 'success'

export function Button({
  variant = 'ghost',
  className = '',
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return <button className={`mq-btn mq-btn-${variant} ${className}`} {...rest} />
}
