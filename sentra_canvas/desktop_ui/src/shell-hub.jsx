import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ChartColumn, ExternalLink, Info, LayoutDashboard, Pencil, Plug, ShieldCheck, Users,
} from 'lucide-react';
import { Modal } from './primitives';
import { DotMascot, DOT_MASCOTS, mascotFor } from './shell-mascot';
import { dotObservation, formatWhen, hubSections } from './shell-hub-state';
import './shell-hub.css';
import coucouLicense from '../../../vendor/coucou/LICENSE?raw';

const TAB_ICONS = {
  overview: LayoutDashboard,
  companions: Users,
  activity: ChartColumn,
  integrations: Plug,
  about: Info,
};

const TAB_COPY = {
  overview: 'Seu projeto, seus Dots e o que está acontecendo.',
  companions: 'Escolha um personagem para o seu Dot.',
  activity: 'Acompanhe o trabalho e os resultados dos últimos 7 dias.',
  integrations: 'Modelos e ferramentas disponíveis neste projeto.',
  about: 'Sobre o SENTRA e esta experiência.',
};

const TONE_LABELS = {
  observed: 'observado',
  waiting: 'aguardando',
  uncertain: 'incerto',
  failed: 'falhou · observado',
  unknown: 'não informado',
  info: 'informativo',
  verified: 'sem recibo verificado',
};

function dotCompanion(dot) {
  const explicit = String(dot?.mascot || '').trim();
  if (DOT_MASCOTS.some(item => item.id === explicit)) return explicit;
  return mascotFor(dot?.dot_id || dot?.name || '');
}

function cardBadge(card) {
  if (card.verified === true) return { label: 'verificado', tone: 'verified' };
  return { label: TONE_LABELS[card.tone] || 'observado', tone: card.tone || 'info' };
}

function HubCard({ item }) {
  const badge = cardBadge(item);
  return (
    <article className="shell-hub-card" data-tone={item.tone || 'info'} data-verified={item.verified === true ? 'true' : 'false'}>
      <header>
        <span className="shell-hub-card-label">{item.label}</span>
        {['verified', 'waiting', 'uncertain', 'failed'].includes(badge.tone) && <span className="shell-hub-badge" data-tone={badge.tone}>
          {badge.tone === 'verified' && <ShieldCheck size={11} aria-hidden="true" />}
          {badge.label}
        </span>}
      </header>
      <strong>{item.value}</strong>
      {item.detail && <p>{item.detail}</p>}
    </article>
  );
}

function sortedEntries(value) {
  return Object.entries(value && typeof value === 'object' ? value : {})
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], 'pt'));
}

function kindSummary(byKind) {
  const rows = sortedEntries(byKind);
  if (!rows.length) return 'nenhum evento';
  return rows.slice(0, 3).map(([kind, count]) => kind + ' · ' + count).join(' · ');
}

export function ShellHub({
  open, onClose, home, dots, events, project, models,
  onEditDot, onNavigate, onTools,
}) {
  const titleRef = useRef(null);
  const wasOpen = useRef(false);
  const [activeTab, setActiveTab] = useState('overview');
  const [preview, setPreview] = useState(DOT_MASCOTS[0]?.id || 'oxta');

  const sections = useMemo(
    () => hubSections({ home, dots, events, project, models }),
    [home, dots, events, project, models],
  );

  const dotRows = useMemo(() => {
    if (Array.isArray(dots)) return dots;
    if (Array.isArray(home?.dots)) return home.dots;
    return [];
  }, [dots, home]);

  useEffect(() => {
    if (open && !wasOpen.current) {
      setActiveTab('overview');
      const first = dotRows.find(dot => dot && typeof dot === 'object');
      setPreview(first ? dotCompanion(first) : (DOT_MASCOTS[0]?.id || 'oxta'));
    }
    wasOpen.current = Boolean(open);
  }, [open, dotRows]);

  const previewMascot = DOT_MASCOTS.some(item => item.id === preview)
    ? preview
    : (DOT_MASCOTS[0]?.id || 'oxta');
  const previewMeta = DOT_MASCOTS.find(item => item.id === previewMascot) || { id: previewMascot, label: previewMascot };
  const previewMatches = dotRows.filter(dot => dot && dotCompanion(dot) === previewMascot);
  const previewDot = previewMatches[0] || null;
  const previewObservation = previewDot ? dotObservation(previewDot) : null;

  const activeMeta = sections.tabs.find(tab => tab.id === activeTab) || sections.tabs[0];
  const navCounts = {
    overview: sections.counts.approvals,
    companions: sections.counts.dots,
    activity: sections.counts.totalEvents,
  };

  const chartDays = [...sections.recap.days].reverse();
  if (sections.recap.undated.count) chartDays.push(sections.recap.undated);
  const chartPeak = Math.max(1, ...chartDays.map(day => day.count));

  function focusTitle(event) {
    event.preventDefault();
    const dialog = event.currentTarget;
    const move = () => {
      const heading = dialog.querySelector('.dialog-heading h2');
      if (heading && typeof heading.focus === 'function') {
        heading.setAttribute('tabindex', '-1');
        heading.focus();
        return;
      }
      titleRef.current?.focus();
    };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(move);
    else setTimeout(move, 0);
  }

  function go(next) {
    if (!onNavigate) return;
    onClose?.();
    onNavigate(next);
  }

  function openApproval(item) {
    if (!item.conversation_id || !onNavigate) return;
    const next = { view: 'chat', conversation_id: item.conversation_id };
    if (item.space_id) next.space_id = item.space_id;
    if (item.dot_id) next.dot_id = item.dot_id;
    go(next);
  }

  function editPreviewDot() {
    if (!previewDot || !onEditDot) return;
    onClose?.();
    onEditDot(previewDot);
  }

  return (
    <Modal
      open={Boolean(open)}
      onOpenChange={value => { if (!value) onClose?.(); }}
      title="Hub SENTRA"
      description="Seu projeto, seus Dots e sua atividade em um só lugar."
      className="shell-modal shell-hub-dialog"
      role="dialog"
      aria-modal="true"
      onOpenAutoFocus={focusTitle}
    >
      <div className="shell-hub">
        <nav className="shell-hub-nav" aria-label="Seções do Hub">
          <p className="shell-hub-nav-label">Navegar</p>
          {sections.tabs.map(tab => {
            const Icon = TAB_ICONS[tab.id] || Info;
            const count = navCounts[tab.id] || 0;
            return (
              <button
                key={tab.id}
                type="button"
                className="shell-hub-nav-button"
                aria-current={activeTab === tab.id ? 'page' : undefined}
                onClick={() => setActiveTab(tab.id)}
              >
                <Icon size={16} aria-hidden="true" />
                <span>{tab.label}</span>
                {count > 0 && <small aria-label={count + ' itens observados'}>{count}</small>}
              </button>
            );
          })}
          <div className="shell-hub-nav-footer">
            <ShieldCheck size={14} aria-hidden="true" />
            <span>Um resumo do seu trabalho.</span>
          </div>
        </nav>

        <section className="shell-hub-main" aria-label={activeMeta.label}>
          <header className="shell-hub-heading">
            <div>
              <p className="shell-hub-eyebrow"><span aria-hidden="true" />Hub · somente leitura</p>
              <h3 ref={titleRef} tabIndex={-1}>{activeMeta.label}</h3>
              <p>{TAB_COPY[activeTab] || TAB_COPY.overview}</p>
            </div>
            {activeTab === 'activity' && (
              <button
                type="button"
                className="shell-hub-primary shell-hub-cta"
                onClick={() => onTools?.('activity')}
                disabled={!onTools}
                title={onTools ? 'Abrir a atividade completa no shell' : 'O host não forneceu onTools.'}
              >
                Abrir atividade <ExternalLink size={14} aria-hidden="true" />
              </button>
            )}
          </header>

          <div className="shell-hub-body">
            {activeTab === 'overview' && (
              <>
                <div className="shell-hub-grid">
                  {sections.overview.map(item => <HubCard key={item.id} item={item} />)}
                </div>

                {sections.approvals.length > 0 && (
                  <section className="shell-hub-block" aria-labelledby="shell-hub-approvals-heading">
                    <header>
                      <div>
                        <h4 id="shell-hub-approvals-heading">Aguardando decisão</h4>
                        <p>O hub apenas mostra e navega. A decisão continua sendo humana.</p>
                      </div>
                      <span className="shell-hub-count">{sections.approvals.length}</span>
                    </header>
                    <ul className="shell-hub-approvals">
                      {sections.approvals.map(item => (
                        <li key={item.id}>
                          <div>
                            <strong>{item.title}</strong>
                            <small>{item.reasonLabel} · {item.source}</small>
                          </div>
                          <button
                            type="button"
                            className="shell-hub-ghost"
                            onClick={() => openApproval(item)}
                            disabled={!item.conversation_id || !onNavigate}
                            title={item.conversation_id ? 'Abrir a conversa relacionada' : 'Esta leitura não trouxe uma conversa relacionada.'}
                          >
                            Abrir conversa <ExternalLink size={13} aria-hidden="true" />
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                )}

                <div className="shell-hub-actions">
                  <button type="button" className="shell-hub-ghost" onClick={() => go({ view: 'home' })} disabled={!onNavigate}>Abrir início</button>
                  <button type="button" className="shell-hub-ghost" onClick={() => go({ view: 'dots' })} disabled={!onNavigate}>Ver Dots</button>
                  <button type="button" className="shell-hub-ghost" onClick={() => go({ view: 'spaces' })} disabled={!onNavigate}>Ver Spaces</button>
                  <button type="button" className="shell-hub-ghost" onClick={() => go({ view: 'documents' })} disabled={!onNavigate}>Documentos</button>
                </div>
              </>
            )}

            {activeTab === 'companions' && (
              <div className="shell-hub-companions">
                <div className="shell-hub-companion-grid" role="group" aria-label="Escolher um companion para a prévia">
                  {DOT_MASCOTS.map(item => {
                    const current = dotRows.find(dot => dot && dotCompanion(dot) === item.id);
                    return (
                      <button
                        key={item.id}
                        type="button"
                        className="shell-hub-companion"
                        aria-pressed={previewMascot === item.id}
                        aria-label={'Pré-visualizar ' + item.label + (current ? ' · usado por ' + current.name : ' · sem Dot')}
                        onClick={() => setPreview(item.id)}
                      >
                        <DotMascot mascot={item.id} size="nav" decorative />
                        <span className="shell-hub-companion-name">{item.label}</span>
                        <small className="shell-hub-companion-dot">{current ? current.name : 'livre'}</small>
                      </button>
                    );
                  })}
                </div>

                <aside className="shell-hub-preview" aria-label={'Prévia de ' + previewMeta.label}>
                  <p className="shell-hub-preview-tag">Prévia local · não persistida</p>
                  <DotMascot
                    mascot={previewMascot}
                    size="hero"
                    name={previewMeta.label}
                    status={previewDot?.status}
                    execution={previewDot?.execution}
                    decorative
                  />
                  <h4>{previewMeta.label}</h4>
                  <p className="shell-hub-preview-dot">
                    Dot atual: {previewDot ? <strong>{previewDot.name}</strong> : <span>nenhum Dot deste Space</span>}
                    {previewMatches.length > 1 && <small> e mais {previewMatches.length - 1}</small>}
                  </p>
                  {previewObservation && (
                    <span className="shell-hub-badge" data-tone={previewObservation.tone}>
                      {previewObservation.verified && <ShieldCheck size={11} aria-hidden="true" />}
                      {previewObservation.label}
                    </span>
                  )}
                  <button
                    type="button"
                    className="shell-hub-primary"
                    onClick={editPreviewDot}
                    disabled={!previewDot || !onEditDot}
                    title={previewDot ? 'Abrir o editor deste Dot' : 'Nenhum Dot deste Space usa este personagem.'}
                  >
                    <Pencil size={14} aria-hidden="true" /> Editar Dot
                  </button>
                  <small className="shell-hub-muted">
                    A escolha acima só muda esta prévia. Nenhum Dot é alterado ou salvo.
                  </small>
                </aside>
              </div>
            )}

            {activeTab === 'activity' && (
              <>
                <div className="shell-hub-grid">
                  {sections.activity.map(item => <HubCard key={item.id} item={item} />)}
                </div>

                <section className="shell-hub-block" aria-labelledby="shell-hub-chart-heading">
                  <header>
                    <div>
                      <h4 id="shell-hub-chart-heading">Eventos por dia</h4>
                      <p>Da data mais antiga para a mais recente; eventos sem data ficam à direita.</p>
                    </div>
                    <span className="shell-hub-count">{sections.recap.window.days} dias</span>
                  </header>
                  <div className="shell-hub-chart" role="group" aria-label="Eventos observados por dia">
                    {chartDays.map(day => {
                      const height = day.count ? Math.max(6, Math.round((day.count / chartPeak) * 100)) : 0;
                      return (
                        <div className="shell-hub-bar" key={day.key} data-undated={day.undated ? 'true' : 'false'}>
                          <div
                            className="shell-hub-bar-track"
                            role="img"
                            aria-label={day.label + ': ' + day.count + (day.count === 1 ? ' evento' : ' eventos') + ', ' + day.verified + ' verificado(s)'}
                          >
                            <span style={{ height: height + '%' }} />
                          </div>
                          <strong>{day.count}</strong>
                          <small>{day.undated ? 'sem data' : day.short}</small>
                        </div>
                      );
                    })}
                  </div>
                </section>

                <section className="shell-hub-block" aria-labelledby="shell-hub-days-heading">
                  <header>
                    <div>
                      <h4 id="shell-hub-days-heading">Dias observados</h4>
                      <p>Contagem bruta da janela. Não é produtividade oficial.</p>
                    </div>
                    <span className="shell-hub-count">{sections.recap.total}</span>
                  </header>
                  <ul className="shell-hub-days">
                    {sections.recap.days.map(day => (
                      <li key={day.key} className="shell-hub-day">
                        <div>
                          <strong>{day.label}</strong>
                          <small>{kindSummary(day.byKind)}</small>
                        </div>
                        <div className="shell-hub-day-meta">
                          <span>{day.count} {day.count === 1 ? 'evento' : 'eventos'}</span>
                          <span data-tone={day.verified ? 'verified' : 'info'}>{day.verified} verificado(s)</span>
                          {day.latest && <time dateTime={new Date(day.latest).toISOString()}>{formatWhen(day.latest)}</time>}
                        </div>
                      </li>
                    ))}
                    {sections.recap.undated.count > 0 && (
                      <li className="shell-hub-day" data-undated="true">
                        <div>
                          <strong>Sem data</strong>
                          <small>{kindSummary(sections.recap.undated.byKind)}</small>
                        </div>
                        <div className="shell-hub-day-meta">
                          <span>{sections.recap.undated.count} evento(s)</span>
                          <span data-tone={sections.recap.undated.verified ? 'verified' : 'info'}>{sections.recap.undated.verified} verificado(s)</span>
                          <time>sem created_at/timestamp</time>
                        </div>
                      </li>
                    )}
                  </ul>
                </section>

                <div className="shell-hub-duo">
                  <section className="shell-hub-block" aria-labelledby="shell-hub-kinds-heading">
                    <header><div><h4 id="shell-hub-kinds-heading">Por tipo</h4><p>Contagem bruta na janela.</p></div></header>
                    {sortedEntries(sections.recap.byKind).length ? (
                      <dl className="shell-hub-kinds">
                        {sortedEntries(sections.recap.byKind).map(([kind, count]) => (
                          <div key={kind}><dt>{kind}</dt><dd>{count}</dd></div>
                        ))}
                      </dl>
                    ) : <p className="shell-hub-empty">Nenhum evento nesta janela.</p>}
                  </section>

                  <section className="shell-hub-block" aria-labelledby="shell-hub-states-heading">
                    <header><div><h4 id="shell-hub-states-heading">Por estado</h4><p>O estado informado não é conclusão.</p></div></header>
                    {sortedEntries(sections.recap.byState).length ? (
                      <dl className="shell-hub-kinds">
                        {sortedEntries(sections.recap.byState).map(([state, count]) => (
                          <div key={state}><dt>{state}</dt><dd>{count}</dd></div>
                        ))}
                      </dl>
                    ) : <p className="shell-hub-empty">Nenhum estado informado nesta janela.</p>}
                  </section>
                </div>
              </>
            )}

            {activeTab === 'integrations' && (
              <>
                <div className="shell-hub-grid">
                  {sections.integrations.map(item => <HubCard key={item.id} item={item} />)}
                </div>

                <section className="shell-hub-block" aria-labelledby="shell-hub-models-heading">
                  <header>
                    <div>
                      <h4 id="shell-hub-models-heading">Modelos anunciados</h4>
                      <p>Anúncio do catálogo; acesso e execução não estão verificados.</p>
                    </div>
                    <span className="shell-hub-count">{sections.models.length}</span>
                  </header>
                  {sections.models.length ? (
                    <div className="shell-hub-pills">
                      {sections.models.map((model, index) => (
                        <span
                          className="shell-hub-pill"
                          key={model.id + ':' + index}
                          data-state={model.available === true ? 'on' : model.available === false ? 'off' : 'unknown'}
                          title={model.id}
                        >
                          <strong>{model.label}</strong>
                          <small>{model.provider || 'provedor não informado'} · {model.available === true ? 'disponível' : model.available === false ? 'indisponível' : 'anunciado'}</small>
                        </span>
                      ))}
                    </div>
                  ) : <p className="shell-hub-empty">Nenhum modelo foi anunciado nesta leitura.</p>}
                </section>

                <div className="shell-hub-duo">
                  <section className="shell-hub-block" aria-labelledby="shell-hub-providers-heading">
                    <header><div><h4 id="shell-hub-providers-heading">Provedores</h4><p>Derivados dos identificadores anunciados.</p></div></header>
                    {sections.providers.length ? (
                      <div className="shell-hub-pills">
                        {sections.providers.map(provider => (
                          <span className="shell-hub-pill" key={provider.id}>
                            <strong>{provider.label}</strong>
                            <small>{provider.count} {provider.count === 1 ? 'modelo' : 'modelos'}</small>
                          </span>
                        ))}
                      </div>
                    ) : <p className="shell-hub-empty">Nenhum provedor pôde ser derivado desta leitura.</p>}
                  </section>

                  <section className="shell-hub-block" aria-labelledby="shell-hub-capabilities-heading">
                    <header><div><h4 id="shell-hub-capabilities-heading">Capacidades concedidas</h4><p>O hub não altera permissões.</p></div></header>
                    {sections.capabilities.length ? (
                      <div className="shell-hub-pills">
                        {sections.capabilities.map((capability, index) => (
                          <span className="shell-hub-pill" key={capability.id + ':' + index}>
                            <strong>{capability.label}</strong>
                            <small>{capability.state || 'estado não informado'}</small>
                          </span>
                        ))}
                      </div>
                    ) : <p className="shell-hub-empty">Nenhuma capacidade concedida foi informada nesta leitura.</p>}
                  </section>
                </div>

                <p className="shell-hub-note">
                  <ShieldCheck size={15} aria-hidden="true" />
                  Nenhum campo de chave ou credencial é lido, exibido ou armazenado por este hub.
                </p>
              </>
            )}

            {activeTab === 'about' && (
              <>
                <div className="shell-hub-grid">
                  {sections.about.map(item => <HubCard key={item.id} item={item} />)}
                </div>
                <section className="shell-hub-block" aria-labelledby="shell-hub-origin-heading">
                  <header><div><h4 id="shell-hub-origin-heading">Origem visual</h4><p>Inspiração declarada, sem cópia de personagens.</p></div></header>
                  <p className="shell-hub-origin">
                    <strong>Visual inspirado no Coucou (MIT); personagens originais do SENTRA.</strong>
                  </p>
                  <ul className="shell-hub-bullets">
                    <li>O Coucou serve como referência de composição, vidro e navegação lateral.</li>
                    <li>Os 17 companions, seus nomes e suas animações são originais do SENTRA.</li>
                    <li>Nenhum asset, som ou personagem do Coucou/Mochi é copiado para esta interface.</li>
                  </ul>
                  <details className="shell-hub-license"><summary>Licença do Coucou (MIT)</summary><pre>{coucouLicense}</pre></details>
                </section>
              </>
            )}
          </div>
        </section>
      </div>
    </Modal>
  );
}

export default ShellHub;
