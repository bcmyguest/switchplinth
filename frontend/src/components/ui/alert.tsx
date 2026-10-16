import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

const alertVariants = cva(
  'relative grid w-full grid-cols-[0_1fr] items-start gap-y-0.5 rounded-lg border px-4 py-3 text-sm has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] has-[>svg]:gap-x-3 [&>svg]:size-4 [&>svg]:translate-y-0.5 [&>svg]:text-current',
  {
    variants: {
      variant: {
        default: 'border-(--theme-line) bg-(--theme-panel) text-(--theme-ink)',
        warning: 'border-(--theme-warning) bg-(--theme-panel) text-(--theme-warning) *:data-[slot=alert-description]:text-(--theme-warning)',
        destructive: 'border-(--theme-danger) bg-(--theme-panel) text-(--theme-danger) *:data-[slot=alert-description]:text-(--theme-danger)',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

type AlertProps = ComponentProps<'div'> & VariantProps<typeof alertVariants>

export function Alert({ className, variant, role, ...props }: AlertProps) {
  const resolvedRole = role ?? (variant === 'warning' || variant === 'destructive' ? 'alert' : 'status')
  return <div data-slot="alert" role={resolvedRole} className={cn(alertVariants({ variant }), className)} {...props} />
}

export function AlertTitle({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="alert-title" className={cn('col-start-2 line-clamp-1 min-h-4 font-medium tracking-tight', className)} {...props} />
}

export function AlertDescription({ className, ...props }: ComponentProps<'div'>) {
  return <div data-slot="alert-description" className={cn('col-start-2 grid justify-items-start gap-1 text-sm text-(--theme-muted) [&_p]:leading-relaxed', className)} {...props} />
}
