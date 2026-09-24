/**
 * Themed Radix DropdownMenu: keyboard navigation, typeahead, focus management and ARIA
 * come from Radix; we only add the look and a quick scale/fade entrance.
 */
import * as DM from '@radix-ui/react-dropdown-menu'
import { Check } from 'lucide-react'
import type { ReactNode } from 'react'

export const Menu = DM.Root
export const MenuTrigger = DM.Trigger

export function MenuContent({
  children,
  align = 'start',
  className = '',
}: {
  children: ReactNode
  align?: 'start' | 'end' | 'center'
  className?: string
}) {
  return (
    <DM.Portal>
      <DM.Content
        align={align}
        sideOffset={6}
        collisionPadding={12}
        className={`menu-content z-50 min-w-44 rounded-card border border-border bg-elevated p-1 text-sm shadow-[var(--shadow-elevated)] ${className}`}
      >
        {children}
      </DM.Content>
    </DM.Portal>
  )
}

const itemClass =
  'relative flex h-8 cursor-default select-none items-center gap-2 rounded-control px-2 text-fg outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-canvas data-[disabled]:opacity-40'

export function MenuItem({
  children,
  onSelect,
  disabled,
  danger = false,
}: {
  children: ReactNode
  onSelect?: () => void
  disabled?: boolean
  danger?: boolean
}) {
  return (
    <DM.Item
      className={`${itemClass} ${danger ? 'text-danger' : ''}`}
      disabled={disabled ?? false}
      {...(onSelect ? { onSelect } : {})}
    >
      {children}
    </DM.Item>
  )
}

export function MenuCheckItem({
  children,
  checked,
  onCheckedChange,
}: {
  children: ReactNode
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  return (
    <DM.CheckboxItem
      className={`${itemClass} pl-7`}
      checked={checked}
      onCheckedChange={onCheckedChange}
      onSelect={(e) => {
        e.preventDefault() // keep the menu open for multi-select
      }}
    >
      <DM.ItemIndicator className="absolute left-2 inline-flex">
        <Check className="size-3.5 text-accent" />
      </DM.ItemIndicator>
      {children}
    </DM.CheckboxItem>
  )
}

export function MenuLabel({ children }: { children: ReactNode }) {
  return <DM.Label className="px-2 pb-1 pt-1.5 text-xs text-fg-muted">{children}</DM.Label>
}

export function MenuSeparator() {
  return <DM.Separator className="my-1 h-px bg-[color:var(--border)]" />
}
