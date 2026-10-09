import React, { forwardRef } from 'react';
import * as Tooltip from '@radix-ui/react-tooltip';
import * as Dialog from '@radix-ui/react-dialog';
import * as Menu from '@radix-ui/react-dropdown-menu';
import { X, MoreHorizontal } from 'lucide-react';

export const IconButton = forwardRef(function IconButton({ label, children, className = '', ...props }, ref) {
  return <Tooltip.Root><Tooltip.Trigger asChild>
    <button ref={ref} type="button" aria-label={label} title={label}
      className={'icon-button ' + className} {...props}>{children}</button>
  </Tooltip.Trigger><Tooltip.Portal><Tooltip.Content className="tooltip" sideOffset={7}>
    {label}<Tooltip.Arrow />
  </Tooltip.Content></Tooltip.Portal></Tooltip.Root>;
});
export function Modal({ open, onOpenChange, title, description, children, className = '', busy = false, ...props }) {
  return <Dialog.Root open={open} onOpenChange={value => { if (!busy) onOpenChange(value); }}>
    <Dialog.Portal><Dialog.Overlay className="dialog-overlay" />
      <Dialog.Content className={'dialog-content ' + className}
        onEscapeKeyDown={e => { if (busy) e.preventDefault(); }}
        onInteractOutside={e => { if (busy) e.preventDefault(); }} {...props}>
        <header className="dialog-heading"><div><Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description></div>
          <Dialog.Close asChild><button type="button" className="icon-button" aria-label="Fechar" disabled={busy}><X size={16} /></button></Dialog.Close>
        </header>{children}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
export function ActionMenu({ label = 'Ações', items, trigger }) {
  return <Menu.Root><Menu.Trigger asChild>{trigger ||
    <button type="button" className="icon-button nodrag" aria-label={label} title={label}><MoreHorizontal size={15} /></button>}
  </Menu.Trigger><Menu.Portal><Menu.Content className="context-menu" sideOffset={6} align="end">
    {items.map((item, i) => item.separator ? <Menu.Separator key={i} className="menu-separator" /> :
      <Menu.Item key={item.label} className={'menu-item ' + (item.danger ? 'danger' : '')}
        disabled={item.disabled} onSelect={item.action}>{item.icon}{item.label}</Menu.Item>)}
  </Menu.Content></Menu.Portal></Menu.Root>;
}
export function Field({ label, hint, children }) {
  return <label className="dialog-field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
