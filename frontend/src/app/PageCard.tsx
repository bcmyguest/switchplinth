import type { ComponentProps } from 'react'
import { Card } from '../components/ui/card'
import { cn } from '../lib/utils'

/** Page-level `<section>` card used by the Architecture log and Progress pages. */
export function PageCard({ className, ...props }: ComponentProps<'section'>) {
  return <Card asChild className={cn('gap-0 rounded-[9px] p-[16px] shadow-none', className)}><section {...props} /></Card>
}
