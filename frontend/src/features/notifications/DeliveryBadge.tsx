import { CheckCircle2, Clock, XCircle } from 'lucide-react'

import type { OutboxStatus } from '@/api/notifications'

const styles: Record<OutboxStatus, { icon: typeof Clock; label: string; className: string }> = {
  pending: {
    icon: Clock,
    label: 'Pending',
    className: 'text-priority-medium bg-priority-medium/10',
  },
  sent: {
    icon: CheckCircle2,
    label: 'Sent',
    className: 'text-status-resolved bg-status-resolved/10',
  },
  failed: { icon: XCircle, label: 'Failed', className: 'text-danger bg-danger/10' },
}

/** Delivery state, always icon + text (never colour alone). */
export function DeliveryBadge({ status, attempts }: { status: OutboxStatus; attempts: number }) {
  const s = styles[status]
  const Icon = s.icon
  const retrying = status === 'pending' && attempts > 0
  return (
    <span
      className={`inline-flex h-6 items-center gap-1 rounded-full px-2 text-xs ${s.className}`}
      title={attempts ? `${attempts} attempt${attempts === 1 ? '' : 's'}` : undefined}
    >
      <Icon aria-hidden className="size-3.5" />
      {retrying ? `Retrying (${attempts})` : s.label}
    </span>
  )
}
