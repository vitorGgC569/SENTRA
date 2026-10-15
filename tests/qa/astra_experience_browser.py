"""Real React components in Chromium; synthetic messages, no inference or live broker."""
from __future__ import annotations
import json
from pathlib import Path
import socket
import subprocess
import time
import urllib.request
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'sentra_canvas' / 'desktop_ui'


def main():
    output = ROOT / '.tmp' / 'astra-experience-qa'
    output.mkdir(parents=True, exist_ok=True)
    with socket.socket() as candidate:
        candidate.bind(('127.0.0.1', 0))
        port = candidate.getsockname()[1]
    log = (output / 'vite.log').open('w', encoding='utf-8')
    server = subprocess.Popen(['node', 'node_modules/vite/bin/vite.js', '--host', '127.0.0.1', '--port', str(port), '--strictPort'], cwd=UI, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    base = f'http://127.0.0.1:{port}/desktop-assets/qa/experience.html'
    try:
        for _ in range(150):
            if server.poll() is not None:
                raise RuntimeError('Vite exited; see ' + str(output / 'vite.log'))
            try:
                urllib.request.urlopen(base, timeout=1).close()
                break
            except OSError:
                time.sleep(.1)
        else:
            raise TimeoutError('QA Vite did not become ready')
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
            context.add_init_script('sessionStorage.setItem("sentra_native_token", "synthetic-qa-token");')
            context.route('**/api/**', lambda route: route.fulfill(status=404 if '/shell/stream' in route.request.url else 200, content_type='application/json', body=json.dumps({'status': 'idle', 'items': [], 'content': ''})))
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(base)
            page.locator('.shell-markdown table').wait_for()
            assert page.locator('.shell-markdown ul ul li').count() == 1, page.locator('.shell-markdown').inner_html()
            assert page.locator('.shell-markdown ol').get_attribute('start') == '3'
            assert page.locator('script').evaluate_all('(nodes)=>nodes.filter(node=>node.textContent.includes("window.hacked=true")).length') == 0
            assert not page.evaluate('Boolean(window.hacked)')
            assert page.locator('a[href^="javascript:"]').count() == 0
            assert page.locator('.shell-markdown img').count() == 0
            assert page.locator('a[href="https://example.com/reference"]').count() == 1
            page.get_by_role('button', name='Copiar código js').click()
            clipboard = page.evaluate('navigator.clipboard.readText()')
            assert clipboard.replace('\r\n', '\n') == 'const mensagem = "Olá 🪐";\nconsole.log(mensagem);', repr(clipboard)
            page.get_by_role('button', name='Copiar código js').focus()
            page.keyboard.press('Enter')
            assert page.evaluate('document.activeElement.getAttribute("aria-label")') == 'Copiar código js'
            page.screenshot(path=str(output / 'markdown-1440.png'), full_page=True)
            # A completed code block must retain its DOM identity as the final paragraph grows.
            stable = page.evaluate('window.savedCode=document.querySelector(".shell-markdown-code"); true')
            page.evaluate('window.setMarkdown(document.querySelector(".shell-markdown").dataset.none || ' + json.dumps('Texto\n\n```js\nconst a = 1;\n```\n\nFinal') + ')')
            page.wait_for_function('document.querySelector("pre code").textContent === "const a = 1;"')
            page.evaluate('window.savedCode=document.querySelector(".shell-markdown-code"); window.setMarkdown(' + json.dumps('Texto\n\n```js\nconst a = 1;\n```\n\nFinal crescendo 🪐') + ')')
            page.wait_for_function('document.body.textContent.includes("Final crescendo")')
            assert page.evaluate('window.savedCode===document.querySelector(".shell-markdown-code")')
            render_samples = page.evaluate('''async () => {
              const prefix = ('Parágrafo concluído com **ênfase** e `código`.\\n\\n').repeat(400);
              window.setMarkdown(prefix + 'Final');
              await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              window.experienceCommits = [];
              for (let index=1; index<=30; index++) {
                window.setMarkdown(prefix + 'Final ' + 'fragmento '.repeat(index));
                await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              }
              return window.experienceCommits.map(item=>item.actualDuration);
            }''')
            assert len(render_samples) >= 20, len(render_samples)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.reload()
            page.locator('table').wait_for()
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.goto(base + '?mode=home')
            page.get_by_role('button', name='Continuar', exact=True).click()
            assert page.evaluate('window.openedConversation') == 'release'
            page.get_by_role('button', name='Consultar', exact=True).click()
            assert page.evaluate('window.openedConversation') == 'uncertain'
            assert page.get_by_text('Envio não confirmado', exact=True).count() == 1
            page.screenshot(path=str(output / 'home-390.png'), full_page=True)
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.screenshot(path=str(output / 'home-1440.png'), full_page=True)
            page.screenshot(path=str(output / 'markdown-390.png'), full_page=True)
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('button').first.evaluate('(node)=>getComputedStyle(node).transitionDuration') == '0s'
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.goto(base + '?mode=window')
            page.locator('[data-windowed=true]').wait_for()
            page.wait_for_timeout(250)
            initial_nodes = page.locator('.shell-message-slot').count()
            assert initial_nodes < 50, initial_nodes
            transcript = page.locator('.shell-transcript')
            transcript.evaluate('(node)=>node.scrollTop=node.scrollHeight/2')
            page.wait_for_timeout(450)
            middle_nodes = page.locator('.shell-message-slot').count()
            assert middle_nodes < 50, middle_nodes
            position = transcript.evaluate('(node)=>node.scrollTop')
            page.evaluate('window.appendWindow()')
            page.wait_for_timeout(250)
            assert abs(transcript.evaluate('(node)=>node.scrollTop') - position) < 2
            anchor_before = page.evaluate('(()=>{ const root=document.querySelector(".shell-transcript").getBoundingClientRect(); return [...document.querySelectorAll(".shell-message-slot")].find(node=>node.getBoundingClientRect().bottom>root.top).dataset.messageId; })()')
            page.evaluate('window.prependWindow()')
            page.wait_for_timeout(350)
            anchor_after = page.evaluate('(()=>{ const root=document.querySelector(".shell-transcript").getBoundingClientRect(); return [...document.querySelectorAll(".shell-message-slot")].find(node=>node.getBoundingClientRect().bottom>root.top).dataset.messageId; })()')
            assert anchor_after == anchor_before, (anchor_before, anchor_after)
            page.screenshot(path=str(output / 'history-window-1440.png'))
            page.get_by_role('button', name='Alternar histórico completo').click()
            page.wait_for_function('document.querySelectorAll(".shell-message-slot").length === 1002')
            page.wait_for_timeout(250)
            complete_anchor = page.evaluate('(()=>{ const root=document.querySelector(".shell-transcript").getBoundingClientRect(); return [...document.querySelectorAll(".shell-message-slot")].find(node=>node.getBoundingClientRect().bottom>root.top).dataset.messageId; })()')
            assert complete_anchor == anchor_after, (anchor_after, complete_anchor)
            page.get_by_role('button', name='Alternar histórico completo').click()
            page.wait_for_timeout(350)
            optimized_anchor = page.evaluate('(()=>{ const root=document.querySelector(".shell-transcript").getBoundingClientRect(); return [...document.querySelectorAll(".shell-message-slot")].find(node=>node.getBoundingClientRect().bottom>root.top).dataset.messageId; })()')
            assert optimized_anchor == complete_anchor, (complete_anchor, optimized_anchor)
            page.goto(base + '?mode=resize')
            handle = page.get_by_role('separator', name='Largura do painel do computador')
            handle.wait_for()
            before = page.locator('aside').bounding_box()['width']
            handle.focus()
            page.keyboard.press('Shift+ArrowLeft')
            page.wait_for_timeout(100)
            after = page.locator('aside').bounding_box()['width']
            assert abs(after - before - 50) < 2, (before, after)
            box = handle.bounding_box()
            page.mouse.move(box['x'] + 4, box['y'] + 100)
            page.mouse.down()
            page.mouse.move(box['x'] - 76, box['y'] + 100, steps=5)
            page.mouse.up()
            page.wait_for_timeout(100)
            dragged = page.locator('aside').bounding_box()['width']
            assert dragged > after + 60, (after, dragged)
            page.reload()
            handle.wait_for()
            assert abs(page.locator('aside').bounding_box()['width'] - dragged) < 2
            page.screenshot(path=str(output / 'computer-resized-1440.png'))
            page.goto(base + '?mode=conversation')
            page.locator('[data-total="100"]').wait_for()
            page.wait_for_timeout(500)
            page.locator('.shell-transcript').evaluate('(node)=>node.scrollTop=100')
            page.get_by_role('button', name='Ir para o mais recente').wait_for()
            before = page.locator('.shell-transcript').evaluate('(node)=>node.scrollTop')
            page.evaluate('window.appendCanonical()')
            page.wait_for_function('document.querySelector(".shell-message-window").dataset.total === "101"')
            assert abs(page.locator('.shell-transcript').evaluate('(node)=>node.scrollTop') - before) < 3
            page.get_by_role('button', name='Ir para o mais recente').click()
            page.wait_for_timeout(350)
            assert page.locator('.shell-transcript').evaluate('(node)=>node.scrollHeight-node.scrollTop-node.clientHeight') < 3
            page.get_by_role('textbox', name='Buscar nas mensagens carregadas').fill('Componente')
            page.locator('[data-total="1"]').wait_for()
            assert page.locator('table').count() == 1
            page.screenshot(path=str(output / 'conversation-search-1440.png'))
            (output / 'conversation-aria.txt').write_text(page.locator('.shell-chat').aria_snapshot(), encoding='utf-8')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(output / 'conversation-markdown-390.png'))
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.evaluate('document.documentElement.dataset.sentraTheme="dark"')
            page.screenshot(path=str(output / 'conversation-dark-390.png'))
            page.evaluate('delete document.documentElement.dataset.sentraTheme')
            page.get_by_role('textbox', name='Buscar nas mensagens carregadas').fill('Não existe resultado')
            page.get_by_role('status').filter(has_text='Nenhuma mensagem carregada').wait_for()
            page.set_viewport_size({'width': 720, 'height': 900})
            page.get_by_role('textbox', name='Buscar nas mensagens carregadas').fill('')
            page.screenshot(path=str(output / 'conversation-zoom-equivalent-720.png'))
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.set_viewport_size({'width': 1440, 'height': 1000})
            page.evaluate('document.documentElement.style.zoom="2"')
            page.screenshot(path=str(output / 'conversation-css-zoom-200.png'))
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            page.evaluate('document.documentElement.style.zoom=""')
            page.set_viewport_size({'width': 390, 'height': 844})
            page.screenshot(path=str(output / 'conversation-390.png'))
            assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
            report = {'synthetic_presentation_data': True, 'model_inference': False, 'production_components': True,
                'markdown_lists_tables_code_copy': True, 'raw_html_and_unsafe_links_inert': True, 'reference_links': True,
                'completed_code_dom_preserved_on_delta': stable, 'loaded_messages_stress': 1000,
                'initial_rendered_messages': initial_nodes, 'middle_rendered_messages': middle_nodes,
                'append_keeps_scroll': True, 'prepend_keeps_reading_anchor': True,
                'full_history_accessible_mode': True, 'computer_resize_pointer_keyboard_persisted': True,
                'conversation_search_and_jump_latest': True, 'horizontal_overflow_390': False,
                'reduced_motion': True, 'css_zoom_200_no_overflow': True,
                'home_resume_and_uncertain_consult_only': True,
                'react_profiler_dev_stream_samples': len(render_samples),
                'react_profiler_dev_stream_p95_ms': round(sorted(render_samples)[int(len(render_samples)*.95)-1], 2),
                'manual_screen_reader_validation': False, 'page_errors': errors}
            (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            assert not errors, errors
            browser.close()
            print(json.dumps(report, ensure_ascii=True))
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill(); server.wait(timeout=5)
        log.close()


if __name__ == '__main__':
    main()
