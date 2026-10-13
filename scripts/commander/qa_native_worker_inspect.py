"""Read-only, metadata-only inspection of this session's browser-action probe."""
import sqlite3
from pathlib import Path
from native_bridge.job_store import JobStore
root=Path(__file__).resolve().parents[2]
uri=(root/'.oma'/'relay.sqlite3').as_uri()+'?mode=ro'
with sqlite3.connect(uri,uri=True) as db:
    rows=db.execute("SELECT id,state,result,worker,phase,may_have_sent FROM jobs WHERE id LIKE ?",
                    ("job_528bdc77%",)).fetchall()
    for jid,state,sealed,worker,phase,effect in rows:
        r=JobStore._unseal(sealed,jid,'result') if sealed else {}
        error=str(r.get('error') or '')
        # Deliberately redact all page contents, paths, URLs and identifiers.
        kinds=('receiving end','message channel','port closed','tab was closed',
               'timeout','unknown operation','not available','not found',
               'permission','unsupported','TAB_ERROR','worker','document','failed')
        import re
        suffix=error.rsplit('TAB_ERROR',1)[-1]
        suffix=re.sub(r'https?://[^\\s]+','[url]',suffix)
        suffix=re.sub(r'[A-Za-z0-9_+/=-]{32,}','[opaque]',suffix)
        print({'state':state,'worker_claimed':bool(worker),'phase':phase,
               'may_have_sent':bool(effect),'error_category':next(
                  (v for v in kinds if v.lower() in error.lower()),'unknown'),
               'sanitized_failure_suffix':suffix[-140:]})
