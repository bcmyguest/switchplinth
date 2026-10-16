import { Slot } from '@radix-ui/react-slot'
import { cva, type VariantProps } from 'class-variance-authority'
import type { ComponentProps } from 'react'
import { cn } from '../../lib/utils'

// The root font size is 13px, so rem-based spacing utilities shrink; these variants use px values. Per-call classes
// override variant classes through `cn` (tailwind-merge). `.ui-button-default` keeps its theme-specific colors in
// map-readability.css because the light primary color has no semantic token.
const buttonVariants = cva('min-h-(--control-target) cursor-pointer text-(length:--type-control) transition-colors duration-150 disabled:cursor-wait', {
  variants: {
    variant: {
      /** Primary action. */
      default: 'ui-button-default inline-flex items-center gap-[6px] rounded-[6px] border px-[11px] font-semibold shadow-[0_1px_2px_#25462d19]',
      secondary: 'border-(--theme-line) bg-(--theme-panel-raised) text-(--theme-ink)',
      ghost: 'bg-transparent',
      /** Secondary action beside a primary one: muted text in light, ink on a raised surface in dark. */
      subtle: 'inline-flex items-center gap-[6px] rounded-[6px] border border-(--theme-line) bg-(--theme-panel) px-[11px] text-(length:--type-tertiary) font-semibold text-(--theme-muted) hover:bg-(--theme-hover) dark:bg-(--theme-panel-raised) dark:text-(--theme-ink) dark:hover:text-(--theme-brand)',
      outline: 'inline-flex items-center gap-[6px] rounded-[6px] border border-(--theme-line) bg-(--theme-panel) px-[11px] font-semibold text-(--theme-ink) hover:bg-(--theme-hover) disabled:cursor-not-allowed disabled:opacity-60',
      link: 'inline-flex items-center gap-[5px] border-0 bg-transparent p-[4px] text-(length:--type-tertiary) font-semibold whitespace-nowrap text-(--theme-source) hover:underline [&>svg]:flex-none',
      /** A bordered row in a list of choices (option previews, history, saved scenarios); `aria-pressed` marks the current one. */
      choice: 'flex items-center gap-[6px] rounded-[5px] border border-(--theme-line) bg-(--theme-panel) px-[9px] py-[7px] text-left text-(--theme-ink) hover:not-disabled:border-(--theme-brand) hover:not-disabled:bg-(--theme-hover) aria-pressed:border-(--theme-brand) aria-pressed:bg-(--theme-selected)',
      /** Borderless muted icon control, for example a panel close button. */
      icon: 'inline-grid place-items-center rounded-[6px] border-0 bg-transparent text-(--theme-muted) hover:bg-(--theme-panel-raised) hover:text-(--theme-ink)',
    },
    size: { default: '', sm: '', icon: 'min-h-0 p-[5px]', tiny: 'px-[8px]' },
  },
  defaultVariants: { variant: 'default', size: 'default' },
})

type ButtonProps = ComponentProps<'button'> & VariantProps<typeof buttonVariants> & { asChild?: boolean }

export function Button({ variant, size, className, asChild = false, ...props }: ButtonProps) {
  const Component = asChild ? Slot : 'button'
  return <Component className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
