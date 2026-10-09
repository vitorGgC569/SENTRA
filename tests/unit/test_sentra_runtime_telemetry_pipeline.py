"""Durable bounded diagnostic queue against an actual loopback HTTP receiver."""
import json
import threading
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer

from sentra_mcp.services.control_store import SQLiteControlPlaneStore
from sentra_runtime.otlp_sink import SafeTelemetryEvent
from sentra_runtime.telemetry_pipeline import TelemetryPipeline


def test_outage_retention_batch_retry_dedup_and_sanitized_payload(tmp_path):
    bodies=[];accept=[False];clock=[100.0]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            bodies.append(self.rfile.read(int(self.headers['Content-Length'])))
            self.send_response(204 if accept[0] else 503);self.end_headers()
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    store=SQLiteControlPlaneStore(tmp_path)
    endpoint=f'http://127.0.0.1:{server.server_port}/v1/traces'
    pipeline=TelemetryPipeline(store,owner='owner',endpoint=endpoint,max_pending=2,batch_size=2,
                               retention_seconds=10,clock=lambda:clock[0],start=False)
    try:
        one=SafeTelemetryEvent('sentra.machine','SUCCEEDED','op-PRIVATE-CONTENT',10)
        two=SafeTelemetryEvent('sentra.machine','FAILED','op-two',20)
        assert pipeline.enqueue(one) and pipeline.enqueue(two)
        assert not pipeline.enqueue(SafeTelemetryEvent('sentra.machine','FAILED','op-overflow'))
        assert pipeline.flush()==0 and pipeline.status()['pending']==2
        assert pipeline.status()['retries']==2 and pipeline.status()['dropped']==1
        pipeline.close()
        pipeline=TelemetryPipeline(store,owner='owner',endpoint=endpoint,max_pending=2,batch_size=2,
                                   retention_seconds=10,clock=lambda:clock[0],start=False)
        accept[0]=True;clock[0]+=2
        assert pipeline.flush()==2
        assert b'PRIVATE-CONTENT' not in bodies[-1]
        assert len(json.loads(bodies[-1])['resourceSpans'])==2
        assert json.loads(bodies[0])==json.loads(bodies[-1])
        assert pipeline.enqueue(one) and pipeline.status()['pending']==0
        assert pipeline.status()['delivered']==2 and pipeline.status()['audit_complete'] is False
        assert pipeline.enqueue(SafeTelemetryEvent('sentra.machine','FAILED','op-expired'))
        clock[0]+=11;pipeline.flush()
        assert pipeline.status()['pending']==0 and pipeline.status()['dropped']==2
    finally:
        pipeline.close();server.shutdown();server.server_close();thread.join(timeout=3)
