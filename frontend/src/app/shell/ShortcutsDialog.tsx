import { Kbd } from '@/components/incident-ui'
import { Modal } from '@/components/Modal'

const SHORTCUTS: { group: string; items: { keys: string[][]; label: string }[] }[] = [
  {
    group: 'Everywhere',
    items: [
      { keys: [['Ctrl', 'K']], label: 'Command palette' },
      { keys: [['C']], label: 'New task' },
      { keys: [['?']], label: 'This list' },
      { keys: [['G', 'D']], label: 'Go to dashboard' },
      { keys: [['G', 'T']], label: 'Go to tasks' },
      { keys: [['G', 'N']], label: 'Go to notifications' },
      { keys: [['G', 'S']], label: 'Go to settings' },
    ],
  },
  {
    group: 'Task list',
    items: [
      { keys: [['J'], ['K']], label: 'Next / previous row' },
      { keys: [['Enter']], label: 'Open the selected task' },
      { keys: [['A']], label: 'Assign the selected task' },
      { keys: [['S']], label: 'Change its status' },
      { keys: [['/']], label: 'Search' },
    ],
  },
  {
    group: 'Writing',
    items: [
      { keys: [['Ctrl', 'Enter']], label: 'Submit a comment or the create form' },
      { keys: [['@']], label: 'Mention someone in a comment' },
      { keys: [['Esc']], label: 'Close a menu, drawer or dialog' },
    ],
  },
]

export function ShortcutsDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  return (
    <Modal open={open} onOpenChange={onOpenChange} title="Keyboard shortcuts" wide>
      <div className="grid gap-6 sm:grid-cols-2">
        {SHORTCUTS.map((section) => (
          <section key={section.group}>
            <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-fg-muted">
              {section.group}
            </h3>
            <dl className="space-y-1.5">
              {section.items.map((item) => (
                <div key={item.label} className="flex items-center justify-between gap-3 text-sm">
                  <dt>{item.label}</dt>
                  <dd className="flex shrink-0 items-center gap-1.5">
                    {item.keys.map((combo, i) => (
                      <span key={combo.join('+')} className="flex items-center gap-1">
                        {i > 0 && <span className="text-xs text-fg-muted">/</span>}
                        {combo.map((k) => (
                          <Kbd key={k}>{k}</Kbd>
                        ))}
                      </span>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
      </div>
    </Modal>
  )
}
