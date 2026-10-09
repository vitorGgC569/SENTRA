"""Read-only product report models + escaped standalone HTML; no UI edits."""
from __future__ import annotations
import html
import json
import math
from pathlib import Path
from urllib.parse import urlsplit
from .rpa import ExecutorFailure,atomic_output


def aggregate_dataset_reports(reports):
    if len(reports)>20000:raise ValueError('dataset_report_count_limit')
    evaluated=[r for r in reports if r.get('evaluated') is True and type(r.get('score')) in (int,float) and math.isfinite(r['score']) and 0<=r['score']<=1]
    groups={}
    for report in reports:
        source=report.get('source',report.get('task',{}));key=(source.get('dataset','unknown'),source.get('category','unknown'))
        group=groups.setdefault(key,{'dataset':key[0],'category':key[1],'total':0,'evaluated':0,'unsupported':0,'scores':[],'latencies':[]})
        group['total']+=1;group['unsupported']+=report.get('state')=='UNSUPPORTED' or report.get('supported') is False
        if report in evaluated:group['evaluated']+=1;group['scores'].append(report['score']);group['latencies'].append(report.get('latency_ms',0))
    for group in groups.values():
        group['mean_score']=sum(group['scores'])/len(group['scores']) if group['scores'] else None
        group['mean_latency_ms']=sum(group['latencies'])/len(group['latencies']) if group['latencies'] else None
        del group['scores'];del group['latencies']
    return {'total':len(reports),'evaluated':len(evaluated),'unsupported':sum(r.get('state')=='UNSUPPORTED' or r.get('supported') is False for r in reports),
            'mean_score':sum(r['score'] for r in evaluated)/len(evaluated) if evaluated else None,
            'success_rate':sum(r['score']==1 for r in evaluated)/len(evaluated) if evaluated else None,
            'denominator':'actually_scored_independent_evaluations_only','groups':list(groups.values()),'reports':reports}


def dataset_report_view_model(report):
    source=report.get('source',report.get('task',{}));verifier=report.get('verifier_result') or {}
    criteria=verifier.get('criteria',[]);artifacts=[]
    for item in [*criteria,*report.get('trajectory',[])]:
        evidence=item.get('evidence',item)
        if evidence.get('artifact_id') or evidence.get('resource_uri'):
            artifacts.append({'artifact_id':evidence.get('artifact_id'),'resource_uri':evidence.get('resource_uri'),
                              'sha256':evidence.get('actual_sha256',evidence.get('sha256'))})
    return {'task_key':source.get('key'),'task_id':source.get('task_id'),'dataset':source.get('dataset'),
        'category':source.get('category'),'source_path':source.get('source_path'),'source_pointer':source.get('source_pointer'),
        'revision':source.get('revision'),'source_file_sha256':source.get('source_file_sha256'),
        'payload_sha256':source.get('payload_sha256'),'state':report.get('state','UNSUPPORTED' if report.get('supported') is False else 'CONFIGURED'),
        'evaluated':report.get('evaluated',False),'score':report.get('score'),'intermediate_score':verifier.get('intermediate_score'),
        'latency_ms':report.get('latency_ms'),'unsupported_reasons':report.get('reasons',[]),'artifacts':artifacts,
        'agent_result':report.get('agent_result'),'verifier_result':verifier,'attempt_id':report.get('attempt_id')}


def render_dataset_report_html(aggregate,*,artifact_href=None):
    """Host resolves authorized Artifact IDs to product routes; no remote embeds."""
    def escape(v):return html.escape('' if v is None else str(v),quote=True)
    rows=[]
    for report in aggregate['reports']:
        model=dataset_report_view_model(report);links=[]
        if artifact_href:
            for artifact in model['artifacts']:
                href=artifact_href(artifact)
                if not isinstance(href,str):continue
                parsed=urlsplit(href)
                if parsed.scheme not in {'','https','http','sentra'} or href.startswith('//'):continue
                links.append('<a href="'+escape(href)+'">'+escape(artifact.get('artifact_id') or 'artifact')+'</a>')
        rows.append('<tr>'+''.join('<td>'+escape(model[k])+'</td>' for k in ('dataset','category','task_id','state','evaluated','score','latency_ms','revision','source_path'))+
                    '<td>'+escape('; '.join(model['unsupported_reasons']))+'</td><td>'+' '.join(links)+'</td></tr>')
    return ('<!doctype html><html lang="pt-BR"><meta charset="utf-8"><title>Avaliação de datasets SENTRA</title>'
        '<style>body{font:14px system-ui;margin:24px}table{border-collapse:collapse;width:100%}td,th{border:1px solid #bbb;padding:8px;text-align:left}td{overflow-wrap:anywhere}</style>'
        '<h1>Avaliação de datasets SENTRA</h1><p>Executados e avaliados: '+escape(aggregate['evaluated'])+
        ' / '+escape(aggregate['total'])+'. Unsupported: '+escape(aggregate['unsupported'])+'. Score médio: '+escape(aggregate['mean_score'])+
        '. Denominador: avaliações independentes efetivamente pontuadas.</p><table><thead><tr>'+
        ''.join('<th>'+h+'</th>' for h in ('Dataset','Categoria','ID','Estado','Evaluated','Score','Latência ms','Revisão','Fonte','Unsupported','Artifacts'))+
        '</tr></thead><tbody>'+''.join(rows)+'</tbody></table></html>')


def publish_dataset_report(aggregate,*,paths,output,source_roots,artifact_href=None):
    target=paths.resolve(output,write=True)
    if any(target.is_relative_to(Path(root).resolve()) for root in source_roots):raise ExecutorFailure('dataset_clone_report_write_denied')
    if target.suffix.lower()=='.json':body=json.dumps(aggregate,ensure_ascii=False,allow_nan=False).encode()
    elif target.suffix.lower()=='.html':body=render_dataset_report_html(aggregate,artifact_href=artifact_href).encode()
    else:raise ValueError('dataset_report_json_or_html_required')
    def verify(path):
        if path.read_bytes()!=body:raise ExecutorFailure('dataset_report_verification_failed')
    return atomic_output(paths,str(target),lambda p:p.write_bytes(body),verify,
                         max_output_bytes=32*1024*1024)
