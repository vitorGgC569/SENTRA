import React from 'react';
import { explainFailure } from './shell-failure';

export function FailureNotice({ message, uncertain = false, onConsult, onDismiss, style }) {
  const copy = explainFailure({ message, uncertain });
  return <div className="shell-failure" role="alert" style={style}>
    <strong>{copy.headline}</strong>
    <p>{copy.happened}</p>
    <p>{copy.safeNext}</p>
    <div>
      {onConsult && <button type="button" onClick={onConsult}>Consultar estado</button>}
      {onDismiss && <button type="button" onClick={onDismiss}>Dispensar aviso</button>}
    </div>
  </div>;
}