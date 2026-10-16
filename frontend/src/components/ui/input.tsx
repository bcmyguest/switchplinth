import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

/** Text input. Sizes use px because the root font size is 13px. */
export function Input({ className, type, ...props }: ComponentProps<'input'>) {
  return <input type={type} data-slot="input" className={cn('flex min-h-(--control-target) w-full min-w-0 rounded-[6px] border border-(--theme-line) bg-(--theme-panel) px-[9px] py-[4px] text-(length:--type-control) text-(--theme-ink) shadow-xs transition-[color,box-shadow] outline-none placeholder:text-(--theme-muted) file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium file:text-(--theme-ink) selection:bg-(--theme-selected) focus-visible:border-(--theme-brand) focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-(--theme-brand) disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-(--theme-danger)', className)} {...props} />
}
