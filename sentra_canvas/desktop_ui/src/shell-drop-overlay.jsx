import React from 'react';
import { DotMascot, DOT_MASCOTS, mascotFor } from './shell-mascot';
import { formatBytes } from './shell-hub-state';
import './shell-drop-overlay.css';

function asArray(value) {
  if (Array.isArray(value)) return value;
  if (!value || typeof value !== 'object') return [];
  if (typeof value.name === 'string') return [];
  if (typeof value[Symbol.iterator] !== 'function') return [];
  try {
    return Array.from(value);
  } catch {
    return [];
  }
}

function listFiles(files) {
  if (!files || typeof files !== 'object') return [];
  if (Array.isArray(files)) return files;
  const nested = asArray(files.files);
  if (nested.length) return nested;
  const items = asArray(files.items);
  if (items.length) return items;
  const direct = asArray(files);
  if (direct.length) return direct;
  return typeof files.name === 'string' ? [files] : [];
}

function fileName(file, index) {
  if (typeof file === 'string') return file.trim() || 'arquivo ' + (index + 1);
  const name = String(file?.name || '').trim();
  return name || 'arquivo ' + (index + 1);
}

/**
 * Overlay visual de drop. Não registra drag/drop e não bloqueia a página:
 * a camada é pointer-events:none e apenas o cartão aceita ponteiro.
 */
export function ShellDropOverlay({ active, files, onClose, dot: dotProp }) {
  if (!active) return null;

  const dot = dotProp && typeof dotProp === 'object'
    ? dotProp
    : (files?.dot && typeof files.dot === 'object' ? files.dot : null);
  const explicit = String(dot?.mascot || '').trim();
  const identity = String(dot?.dot_id || dot?.name || '').trim();
  const mascot = DOT_MASCOTS.some(item => item.id === explicit)
    ? explicit
    : identity
      ? mascotFor(identity)
      : 'oxta';

  const rows = listFiles(files);
  const visible = rows.slice(0, 3);
  const extra = Math.max(0, rows.length - visible.length);
  const summary = rows.length === 0
    ? 'A prévia mostra até 3 nomes e tamanhos.'
    : rows.length === 1
      ? '1 arquivo na prévia.'
      : rows.length + ' arquivos na prévia.';

  return (
    <aside className="shell-drop-overlay" aria-label="Prévia de anexos para soltar">
      <div className="shell-drop-card">
        <span className="shell-drop-visual">
          <DotMascot
            mascot={mascot}
            size="card"
            name={dot?.name || 'Dot'}
            status={dot?.status}
            execution={dot?.execution}
            decorative
          />
        </span>
        <div className="shell-drop-copy">
          <strong>Solte para anexar</strong>
          <p role="status" aria-live="polite">{summary}</p>
          {visible.length > 0 && (
            <ul className="shell-drop-files">
              {visible.map((file, index) => (
                <li key={fileName(file, index) + ':' + index}>
                  <span title={fileName(file, index)}>{fileName(file, index)}</span>
                  <small>{formatBytes(typeof file === 'object' ? file?.size : undefined)}</small>
                </li>
              ))}
            </ul>
          )}
          {extra > 0 && <small className="shell-drop-extra">e mais {extra} arquivo{extra === 1 ? '' : 's'} nesta prévia</small>}
        </div>
        <button
          type="button"
          className="shell-drop-close"
          onClick={() => onClose?.()}
          disabled={!onClose}
          title={onClose ? 'Esconder a prévia de anexos' : 'O host não forneceu onClose.'}
        >
          Esconder prévia
        </button>
      </div>
    </aside>
  );
}

export default ShellDropOverlay;
