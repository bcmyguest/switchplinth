import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

/** Native radio input in the brand accent; radios that share one `name` form a group, so arrow keys move between them. */
export function Radio({ className, ...props }: Omit<ComponentProps<'input'>, 'type'>) {
  return <input type="radio" data-slot="radio" className={cn('mt-[2px] accent-(--theme-brand)', className)} {...props} />
}
