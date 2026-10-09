/* Uses the actual guacamole-common-js supplied by the host, not a renderer mock. */
export function liveViewer(Guacamole, scopedWebSocketURL, container) {
    const tunnel = new Guacamole.WebSocketTunnel(scopedWebSocketURL);
    const client = new Guacamole.Client(tunnel);
    container.replaceChildren(client.getDisplay().getElement());
    // No automatic keyboard/mouse/clipboard hookup. Host chooses a control
    // capability explicitly; backend remains the authority for each instruction.
    client.connect('');
    return { client, tunnel, close() { client.disconnect(); } };
}

export function offlineRecording(Guacamole, recordingDocument, container) {
    if (recordingDocument.provider !== 'guacamole' || !Array.isArray(recordingDocument.events))
        throw new Error('Not a Guacamole artifact');
    const tunnel = new Guacamole.Tunnel();
    // Playback cannot send to any live endpoint: this tunnel owns no transport.
    tunnel.sendMessage = function () {};
    const recording = new Guacamole.SessionRecording(tunnel);
    const parser = new Guacamole.Parser();
    parser.oninstruction = (opcode, args) => tunnel.oninstruction?.(opcode, args);
    const decoder = new TextDecoder('utf-8', { fatal: true });
    let previous = null;
    for (const event of recordingDocument.events) {
        if (previous === null && event.sequence !== 1)
            throw new Error('Recording initial state was evicted; full replay unavailable');
        if (previous !== null && event.sequence !== previous + 1)
            throw new Error('Incomplete recording: sequence gap');
        previous = event.sequence;
        if (event.channel === 'gap') throw new Error('Recording contains a reconnect gap');
        if (event.channel !== 'guacamole') continue;
        const bytes = Uint8Array.from(atob(event.data_base64), ch => ch.charCodeAt(0));
        parser.receive(decoder.decode(bytes, { stream: true }));
    }
    parser.receive(decoder.decode());
    container.replaceChildren(recording.getDisplay().getElement());
    return { recording, play: () => recording.play(), pause: () => recording.pause(),
        seek: ms => recording.seek(ms), position: () => recording.getPosition(),
        completenessAsserted: recordingDocument.completeness_asserted === true };
}
