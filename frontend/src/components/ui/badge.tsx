import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

const badgeVariants = cva(
  'inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--theme-brand) [&>svg]:pointer-events-none [&>svg]:size-3 [a&]:underline-offset-2 [a&]:hover:underline',
  {
    variants: {
      variant: {
        default: 'border-transparent bg-(--theme-brand) text-(--theme-panel)',
        secondary: 'border-transparent bg-(--theme-brand-soft) text-(--theme-ink)',
        warning: 'border-(--theme-warning) bg-(--theme-panel-raised) text-(--theme-warning)',
        destructive: 'border-(--theme-danger) bg-(--theme-panel-raised) text-(--theme-danger)',
        outline: 'border-(--theme-line) text-(--theme-ink)',
      },
    },
    defaultVariants: { variant: 'default' },
  },
)

type BadgeProps = ComponentProps<'span'> & VariantProps<typeof badgeVariants> & { asChild?: boolean }

export function Badge({ className, variant, asChild = false, ...props }: BadgeProps) {
  const Component = asChild ? Slot : 'span'
  return <Component data-slot="badge" className={cn(badgeVariants({ variant }), className)} {...props} />
}
