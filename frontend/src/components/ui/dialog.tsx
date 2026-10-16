import * as DialogPrimitive from '@radix-ui/react-dialog'
import type { ReactNode } from 'react'

type DialogProps = {
  open: boolean
  onOpenChange: (open: boolean) => void
  ariaLabel: string
  children: ReactNode
  onCloseAutoFocus?: (event: Event) => void
}

export function Dialog({ open, onOpenChange, ariaLabel, children, onCloseAutoFocus }: DialogProps) {
  return <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="modal-backdrop" />
      <DialogPrimitive.Content className="dialog-content" aria-label={ariaLabel} onCloseAutoFocus={onCloseAutoFocus}>
        <DialogPrimitive.Title className="sr-only">{ariaLabel}</DialogPrimitive.Title>
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  </DialogPrimitive.Root>
}
