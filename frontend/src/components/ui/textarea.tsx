import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

/** Multi-line text input. Sizes use px because the root font size is 13px; it keeps a fixed height that the user can resize. */
export function Textarea({ className, ...props }: ComponentProps<'textarea'>) {
  return <textarea data-slot="textarea" className={cn('block min-h-[64px] w-full min-w-0 rounded-[6px] border border-(--theme-line) bg-(--theme-panel) px-[9px] py-[6px] text-(length:--type-control) text-(--theme-ink) shadow-xs transition-[color,box-shadow] outline-none placeholder:text-(--theme-muted) selection:bg-(--theme-selected) focus-visible:border-(--theme-brand) focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-(--theme-brand) disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-(--theme-danger)', className)} {...props} />
}
