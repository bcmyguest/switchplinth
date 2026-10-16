import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

// The root font size is 13px, so rem-based spacing utilities shrink; these variants use px values.
// App CSS is unlayered, so `.ui-button-base` and the global `button` rule beat Tailwind utilities; the Tailwind-only variants
// below mark their conflicting properties `!`.
const buttonVariants = cva('ui-button-base', {
  variants: {
    variant: {
      default: 'ui-button-default',
      secondary: 'ui-button-secondary',
      ghost: 'ui-button-ghost',
      outline: 'inline-flex! items-center gap-[6px]! rounded-[6px] border border-(--theme-line) bg-(--theme-panel)! px-[11px]! text-(length:--type-control)! font-semibold! text-(--theme-ink)! hover:bg-(--theme-hover)! disabled:cursor-not-allowed! disabled:opacity-60',
      link: 'inline-flex! items-center gap-[5px]! border-0 bg-transparent! p-[4px]! text-(length:--type-tertiary)! font-semibold! whitespace-nowrap text-(--theme-source)! hover:underline [&>svg]:flex-none',
    },
    size: { default: 'ui-button-size-default', sm: 'ui-button-size-sm', icon: 'ui-button-size-icon' },
  },
  defaultVariants: { variant: 'default', size: 'default' },
})

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants> & { asChild?: boolean }

export function Button({ variant, size, className, asChild = false, ...props }: ButtonProps) {
  const Component = asChild ? Slot : 'button'
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
