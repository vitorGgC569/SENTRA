import React, { useEffect, useRef, useState } from 'react';
import { Mic, PhoneOff } from 'lucide-react';
import { Status } from './shell-receipts';

// Media is opt-in per call. The central bridge negotiates with the configured provider.
export function ShellVoice({ bridge, scope, availability }) {
  const [call, setCall] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState('');
  const [transcript, setTranscript] = useState([]), [muted, setMuted] = useState(false);
  const peer = useRef(null), media = useRef(null), audio = useRef(null), current = useRef(null), alive = useRef(true);
  const starting = useRef(false), stopping = useRef(false), operation = useRef(0), submitted = useRef(false);
  const enabled = availability?.available === true;
  const key = 'sentra_shell_call:' + scope.project_id + ':' + scope.conversation_id;
  function release() {
    media.current?.getTracks().forEach(track => track.stop()); media.current = null;
    peer.current?.close(); peer.current = null;
    if (audio.current) audio.current.srcObject = null;
  }
  useEffect(() => {
    alive.current = true;
    try {
      const saved = JSON.parse(sessionStorage.getItem(key));
      if (saved) { current.current = saved; setCall({ ...saved, status: 'interrupted' }); }
    } catch { /* Optional recovery preference. */ }
    const cleanup = () => release(); addEventListener('pagehide', cleanup);
    return () => { alive.current = false; operation.current++; release(); removeEventListener('pagehide', cleanup); };
  }, [key]);
  useEffect(() => {
    if (!enabled && current.current) release();
  }, [enabled]);
  useEffect(() => {
    if (!call || ['stopped', 'revoked', 'completed', 'failed'].includes(call.status)) return;
    let cancelled = false, fetching = false;
    const observe = async () => {
      if (fetching || document.hidden) return;
      fetching = true;
      try {
        const value = await bridge({ action: 'voice_status', ...scope, call_id: call.call_id,
          start_request_key: call.request_key });
        if (cancelled) return;
        setCall(old => ({ ...old, ...value })); setTranscript(value.transcript || []);
        if (current.current && value.call_id) {
          current.current = { ...current.current, call_id: value.call_id, status: value.status, generation: value.generation };
          sessionStorage.setItem(key, JSON.stringify(current.current));
        }
        if (['stopped', 'revoked', 'expired', 'completed', 'failed'].includes(value.status)) {
          release(); current.current = null; sessionStorage.removeItem(key);
        }
      } catch (e) { if (!cancelled) setError(e.message); } finally { fetching = false; }
    };
    const timer = setInterval(observe, 2500); void observe();
    return () => { cancelled = true; clearInterval(timer); };
  }, [call?.call_id, call?.request_key, call?.status]);
  useEffect(() => {
    if (!call?.call_id || call.status !== 'active') return;
    const heartbeat = async () => {
      if (peer.current?.connectionState !== 'connected' || !media.current) return;
      try { await bridge({ action: 'voice_signal', ...scope, call_id: call.call_id, kind: 'heartbeat', generation: current.current?.generation, request_key: crypto.randomUUID() }); }
      catch (e) { if (alive.current) setError(e.message); }
    };
    const timer = setInterval(heartbeat, 20000);
    return () => clearInterval(timer);
  }, [call?.call_id, call?.status]);
  async function start() {
    if (starting.current || busy || current.current || !enabled) return;
    starting.current = true; submitted.current = false;
    const generation = ++operation.current;
    setBusy(true); setError('');
    const requestKey = crypto.randomUUID();
    try {
      if (!navigator.mediaDevices?.getUserMedia || !window.RTCPeerConnection) throw Error('WebRTC/microfone indisponível nesta superfície.');
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      if (!alive.current || generation !== operation.current) { stream.getTracks().forEach(track => track.stop()); return; }
      media.current = stream;
      const iceServers = (availability.ice_servers || []).map(server => typeof server === 'string' ? { urls: server } : server)
        .filter(server => server?.urls && (typeof server.urls === 'string' ? /^(stun|stuns|turn|turns):/.test(server.urls) : Array.isArray(server.urls)));
      const connection = new RTCPeerConnection({ iceServers }); peer.current = connection;
      for (const track of stream.getTracks()) connection.addTrack(track, stream);
      connection.ontrack = event => { if (audio.current) audio.current.srcObject = event.streams[0] || new MediaStream([event.track]); };
      connection.onconnectionstatechange = () => {
        if (alive.current && ['failed', 'disconnected'].includes(connection.connectionState)) setError('Conexão de voz interrompida. Pare ou revogue a chamada para liberar o serviço.');
      };
      await connection.setLocalDescription(await connection.createOffer());
      if (connection.iceGatheringState !== 'complete') await new Promise((resolve, reject) => {
        const timer = setTimeout(() => { connection.removeEventListener('icegatheringstatechange', changed); reject(Error('A negociação de voz excedeu o prazo.')); }, 10000);
        function changed() { if (connection.iceGatheringState === 'complete') { clearTimeout(timer); connection.removeEventListener('icegatheringstatechange', changed); resolve(); } }
        connection.addEventListener('icegatheringstatechange', changed); changed();
      });
      const pending = { request_key: requestKey, status: 'uncertain' };
      current.current = pending; sessionStorage.setItem(key, JSON.stringify(pending));
      setCall(pending);
      submitted.current = true;
      const result = await bridge({ action: 'voice_start', ...scope, request_key: requestKey,
        offer_sdp: connection.localDescription.sdp, microphone_opt_in: true });
      if (!alive.current || generation !== operation.current) {
        release();
        if (result.call_id) {
          try { await bridge({ action: 'voice_revoke', ...scope, call_id: result.call_id, start_request_key: requestKey, request_key: crypto.randomUUID() }); }
          catch { sessionStorage.setItem(key, JSON.stringify({ call_id: result.call_id, request_key: requestKey, status: 'uncertain' })); }
        }
        return;
      }
      current.current = { call_id: result.call_id, request_key: requestKey, status: result.status, generation: result.generation };
      sessionStorage.setItem(key, JSON.stringify(current.current));
      setCall(current.current); setTranscript(result.transcript || []);
      if (!result.call_id || !result.answer_sdp) throw Error(result.reason || 'O provedor não retornou negociação WebRTC completa.');
      await connection.setRemoteDescription({ type: 'answer', sdp: result.answer_sdp });
    } catch (e) {
      release(); if (alive.current) setError(e.message);
      if ((!submitted.current || (e.status >= 400 && e.status < 500)) && !current.current?.call_id) { current.current = null; setCall(null); sessionStorage.removeItem(key); }
    } finally { starting.current = false; if (alive.current) setBusy(false); }
  }
  async function stop(revoke = false) {
    if (!current.current || stopping.current) return;
    stopping.current = true; operation.current++;
    release(); setBusy(true); setError('');
    try {
      if (!current.current.call_id) {
        const status = await bridge({ action: 'voice_status', ...scope, start_request_key: current.current.request_key });
        if (!status.call_id) throw Error('A chamada ainda não foi identificada. Consulte o estado antes de repetir.');
        current.current.call_id = status.call_id;
      }
      const stopField = revoke ? 'revoke_key' : 'stop_key';
      const result = await bridge({ action: revoke ? 'voice_revoke' : 'voice_stop', ...scope,
        call_id: current.current.call_id, start_request_key: current.current.request_key,
        request_key: current.current[stopField] || (current.current[stopField] = crypto.randomUUID()) });
      setCall(old => ({ ...old, ...result })); current.current = null; sessionStorage.removeItem(key);
    } catch (e) { setError(e.message); sessionStorage.setItem(key, JSON.stringify(current.current)); }
    finally { stopping.current = false; if (alive.current) setBusy(false); }
  }
  return <details className="shell-voice"><summary><Mic size={14} /> Conversar por voz</summary>
    {!enabled && <p>{availability?.reason || 'Voz desativada: configure um provedor WebRTC autorizado.'}</p>}
    {enabled && !current.current && <div><p>Ao iniciar, você permite transmitir o microfone ao provedor {availability.provider || 'configurado'} nesta conversa.</p>
      <button disabled={busy} onClick={start}><Mic size={14} /> Permitir microfone e iniciar</button></div>}
    {call && <div><Status value={call.status} /><button disabled={stopping.current || !current.current} onClick={() => stop()}><PhoneOff size={14} /> Parar</button>
      <button disabled={stopping.current || !current.current} onClick={() => stop(true)}>Revogar chamada</button>
      {media.current && <button onClick={() => { const next = !muted; media.current?.getAudioTracks().forEach(track => { track.enabled = !next; }); setMuted(next); }}>{muted ? 'Ativar microfone' : 'Silenciar microfone'}</button>}</div>}
    {error && <p role="alert" className="shell-error">{error}</p>}
    <audio autoPlay controls ref={audio} aria-label="Áudio da chamada" hidden={!call} />
    {!!transcript.length && <div className="shell-voice-transcript" role="log" aria-live="polite">{transcript.map((entry, index) => <p key={entry.message_id || entry.id || index}><strong>{entry.role || 'Voz'}: </strong>{entry.content || entry.text || ('Segmento registrado: ' + entry.content_chars + ' caracteres. Texto não disponibilizado pelo provedor.')}</p>)}</div>}
  </details>;
}
