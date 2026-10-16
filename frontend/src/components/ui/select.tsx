import * as SelectPrimitive from '@radix-ui/react-select'
import { Children, isValidElement, type ChangeEvent, type ReactElement, type ReactNode, type SelectHTMLAttributes } from 'react'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '../../lib/utils'

type OptionProps = { value?: string; children?: ReactNode }
type SelectProps = Omit<SelectHTMLAttributes<HTMLSelectElement>, 'onChange' | 'children'> & {
  onChange?: (event: ChangeEvent<HTMLSelectElement>) => void
  children?: ReactNode
}

export function Select({ value, onChange, className, children, ...props }: SelectProps) {
  const options = Children.toArray(children).filter((child): child is ReactElement<OptionProps> => isValidElement<OptionProps>(child))
  const placeholder = options.find((option) => option.props.value === '')?.props.children
  const visibleOptions = options.filter((option) => option.props.value !== '')

  return <SelectPrimitive.Root value={String(value ?? '')} onValueChange={(next) => onChange?.({ target: { value: next } } as ChangeEvent<HTMLSelectElement>)}>
    <SelectPrimitive.Trigger className={cn('ui-select-trigger inline-flex min-h-(--control-target) cursor-pointer items-center justify-between gap-[7px] text-left text-(length:--type-control) aria-expanded:border-(--theme-brand)', className)} aria-label={props['aria-label']} disabled={props.disabled}>
      <SelectPrimitive.Value placeholder={placeholder ?? 'Select an option'} />
      <SelectPrimitive.Icon><ChevronDown size={13} /></SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content className="ui-select-content" position="popper" sideOffset={4}>
        <SelectPrimitive.Viewport>{visibleOptions.map((option, index) => <SelectPrimitive.Item className="ui-select-item" key={`${option.props.value}-${index}`} value={option.props.value ?? ''}>
          <SelectPrimitive.ItemText>{option.props.children}</SelectPrimitive.ItemText>
          <SelectPrimitive.ItemIndicator><Check size={12} /></SelectPrimitive.ItemIndicator>
        </SelectPrimitive.Item>)}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  </SelectPrimitive.Root>
}
