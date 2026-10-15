"""Actual Canvas/SSE/DPAPI and browser; synthetic text, no model/account I/O."""
from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from sentra_canvas.__main__ import CanvasServer
from sentra_canvas.service import Canvas


def main():
    output = ROOT / '.tmp' / 'astra-stream-qa'
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='sentra-astra-qa-', ignore_cleanup_errors=True) as temporary:
        base = Path(temporary)
        project_root = base / 'project'
        project_root.mkdir()
        app = Canvas(project_root, principal='astra-qa', state_dir=base / 'state' / 'canvas')
        app.model_catalog = lambda: {'models': ['sentra/test-one']}
        server = CanvasServer(app, 0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            project = app.create_workspace('ASTRA_QA')['id']
            def call(action, **fields):
                return app.shell_bridge({'action': action, 'project_id': project,
                    'request_key': 'qa-' + uuid.uuid4().hex, **fields})['value']
            space = call('home')['space']['space_id']
            dot = call('dot_create', space_id=space, name='Astra QA', role='specialist', model='sentra/test-one')
            conversation = call('conversation_create', space_id=space, dot_id=dot['dot_id'])['conversation_id']
            app._shell_runtime._execute = lambda _operation: None
            operation = call('message_send', space_id=space, conversation_id=conversation,
                content='Teste de interface com produtor sintético, sem inferência.')['operation_id']
            navigation = {'view': 'chat', 'project_id': project, 'space_id': space, 'conversation_id': conversation, 'dot_id': dot['dot_id']}
            journal = app._shell_runtime.stream
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                context = browser.new_context(viewport={'width': 1440, 'height': 1000})
                context.add_init_script('localStorage.setItem("sentra_shell_navigation", ' + json.dumps(json.dumps(navigation)) + ');')
                errors, reads = [], []
                def new_page():
                    page = context.new_page()
                    page.on('pageerror', lambda error: errors.append(str(error)[:200]))
                    page.on('request', lambda req: reads.append(req.url.split('?')[0].split('/')[-1]) if '/api/shell/' in req.url else None)
                    page.goto(f'http://127.0.0.1:{server.server_port}/desktop.html#token={server.secret}')
                    page.wait_for_selector('.shell-chat-stream-status[data-state=connected]', timeout=20000)
                    return page
                page = new_page()
                before = reads.count('live')
                text = 'Resposta de teste com Unicode 🪐 e texto repetido: haha.'
                started = time.monotonic()
                journal.publish(project, space, conversation, {
                    'operation_id': operation, 'status': 'generating', 'activity': 'Recebendo resposta',
                    'content_revision': 0, 'content': text,
                })
                page.wait_for_function('(text) => document.querySelector(".shell-live-preview")?.textContent.includes(text)', arg=text)
                sample_ms = (time.monotonic() - started) * 1000
                journal.publish(project, space, conversation, {
                    'operation_id': operation, 'status': 'confirming', 'activity': 'Confirmando entrega',
                    'content_revision': 0, 'content': text,
                })
                page.wait_for_function('() => document.querySelector(".shell-live-preview")?.textContent.includes("Confirmando entrega")')
                assert text in page.locator('.shell-live-preview').inner_text()
                page.wait_for_timeout(1100)
                assert reads.count('live') == before, 'Legacy preview HTTP polling continued with SSE connected'
                legacy_after_connected = reads.count('live') - before
                page.screenshot(path=str(output / 'chat-confirming-1440.png'), full_page=True)
                page.close()
                page = new_page()
                page.wait_for_function('(text) => document.querySelector(".shell-live-preview")?.textContent.includes(text)', arg=text)
                assert 'Confirmando entrega' in page.locator('.shell-live-preview').inner_text()
                page.set_viewport_size({'width': 390, 'height': 844})
                page.keyboard.press('Escape')
                page.screenshot(path=str(output / 'chat-reopened-390.png'), full_page=True)
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                broken_images = page.locator('img').evaluate_all('(images) => images.filter(i => i.complete && i.naturalWidth === 0).length')
                context.route('**/desktop-assets/*.png', lambda route: route.abort())
                page.reload()
                page.locator('.shell-chat-heading .shell-mascot-fallback').wait_for(state='visible', timeout=10000)
                fallback_rendered = page.locator('.shell-chat-heading .shell-mascot-fallback').is_visible()
                page.screenshot(path=str(output / 'chat-fallback-390.png'), full_page=True)
                report = {'producer': 'synthetic', 'model_inference': False, 'http_server': 'production CanvasServer',
                    'sse_connected': True, 'text_preserved_while_confirming': True, 'reopened_window_restores_snapshot': True,
                    'legacy_preview_requests_after_connected': legacy_after_connected,
                    'single_publish_to_dom_sample_ms': round(sample_ms, 2), 'horizontal_overflow_390': overflow,
                    'broken_images': broken_images, 'fallback_rendered_for_failed_assets': fallback_rendered,
                    'page_errors': errors}
                (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                browser.close()
                assert not errors, errors
                assert not overflow
                assert not broken_images
                assert fallback_rendered
                print(json.dumps(report, ensure_ascii=True))
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
            app.shutdown()


if __name__ == '__main__':
    main()
