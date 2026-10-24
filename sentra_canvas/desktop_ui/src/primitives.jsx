import React, { forwardRef, useRef } from 'react';
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
export function Modal({ open, onOpenChange, title, description, children, className = '', busy = false, onCloseAutoFocus, ...props }) {
  const focusReturn = useRef({ open: false, target: null });
  // Capture before the portal's inputs autofocus, including conditionally mounted dialogs.
  if (open && !focusReturn.current.open && typeof document !== 'undefined') {
    const active = document.activeElement;
    const menu = active?.closest('[role="menu"]');
    const menuTrigger = menu?.id && Array.from(document.querySelectorAll('[aria-controls]'))
      .find(element => element.getAttribute('aria-controls') === menu.id);
    focusReturn.current.target = menuTrigger || active;
  }
  focusReturn.current.open = open;
  return <Dialog.Root open={open} onOpenChange={value => { if (!busy) onOpenChange(value); }}>
    <Dialog.Portal><Dialog.Overlay className="dialog-overlay" />
      <Dialog.Content className={'dialog-content dialog-content-refined ' + className}
        onEscapeKeyDown={e => { if (busy) e.preventDefault(); }}
        onInteractOutside={e => { if (busy) e.preventDefault(); }} {...props}
        onCloseAutoFocus={event => {
          onCloseAutoFocus?.(event);
          const target = focusReturn.current.target;
          if (!event.defaultPrevented && target?.isConnected && target !== document.body
              && !target.matches(':disabled') && !target.closest('[hidden], [inert]')) {
            event.preventDefault();
            target.focus({ preventScroll: true });
          }
        }}>
        <header className="dialog-heading dialog-heading-compact"><div className="dialog-heading-copy"><Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description></div>
          <Dialog.Close asChild><button type="button" className="icon-button dialog-close" aria-label="Fechar" disabled={busy}><X size={16} /></button></Dialog.Close>
        </header>{children}
      </Dialog.Content>
    </Dialog.Portal>
  </Dialog.Root>;
}
export function ActionMenu({ label = 'Ações', items, trigger, open, onOpenChange, side = 'bottom', align = 'end', sideOffset = 10, className = '', heading }) {
  return <Menu.Root open={open} onOpenChange={onOpenChange}><Menu.Trigger asChild>{trigger ||
    <button type="button" className="icon-button nodrag" aria-label={label} title={label}><MoreHorizontal size={15} /></button>}
  </Menu.Trigger><Menu.Portal><Menu.Content className={'context-menu ' + className} side={side} sideOffset={sideOffset} align={align} collisionPadding={16} sticky="always">
    {heading && <Menu.Label className="context-menu-heading">{heading}</Menu.Label>}
    {items.map((item, i) => item.separator ? <Menu.Separator key={i} className="menu-separator" /> :
      <Menu.Item key={item.label} className={'menu-item ' + (item.danger ? 'danger' : '')}
        disabled={item.disabled} onSelect={item.action}>{item.icon}{item.label}</Menu.Item>)}
  </Menu.Content></Menu.Portal></Menu.Root>;
}
export function Field({ label, hint, children }) {
  return <label className="dialog-field"><span className="dialog-field-label">{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}
