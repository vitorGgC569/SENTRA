import React from 'react';
import { presentOptional } from './shell-optional.js';

export function OptionalSurfaces({ document }) {
  const view = presentOptional(document);
  return <section className="shell-optional" aria-label="Marketplace e opt-in" data-homologated="false" data-closed-by-absence="false">
    <h2>Catálogo</h2>
    {view.readFailure ? <p>A consulta do catálogo não chegou.</p>
      : view.connectors?.length || view.models?.length || view.catalog?.length ? <>
        {view.connectors?.map(row => <p key={row.id}><strong>{row.id}</strong> {row.enabled ? 'Habilitado' : 'Não habilitado'} {row.account_present ? '' : row.account_needs}</p>)}
        {view.models?.map(row => <p key={row.id}><strong>{row.id}</strong> {row.reason}</p>)}
        {view.catalog?.map(name => <p key={name}>{name}</p>)}
      </> : view.items.length ? <ul>{view.items.map(item => <li key={item.surface} data-present={String(item.present)}>
        <strong>{item.surface}</strong>
        <span>{item.present ? 'Neste computador' : 'Ainda não está neste computador'}</span>
        <small>{item.needs}</small>
      </li>)}</ul> : <p>Nenhum conector, modelo ou item de catálogo nesta consulta.</p>}
  </section>;
}
