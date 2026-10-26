"""Browser acceptance for the isolated desktop pairing dialog.

All control requests are intercepted in the page. The fixture does not contact
or alter the owner's Canvas, paired devices, profiles or local network.
"""
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
from urllib.error import URLError
from urllib.request import urlopen

import pytest

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / 'sentra_canvas' / 'desktop_ui'
VITE = UI / 'node_modules' / 'vite' / 'bin' / 'vite.js'


@pytest.fixture(scope='module')
def fixture_url():
    node = shutil.which('node')
    if not node or not VITE.is_file():
        pytest.skip('desktop fixture requires installed Node and Vite dependencies')
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    process = subprocess.Popen([node, str(VITE), '--host', '127.0.0.1', '--port', str(port), '--strictPort'],
                               cwd=UI, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    url = f'http://127.0.0.1:{port}/desktop-assets/test/mobile-devices-fixture.html'
    try:
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                pytest.fail('isolated Vite fixture exited before becoming ready')
            try:
                with urlopen(url, timeout=1) as response:
                    if response.status == 200:
                        break
            except (OSError, URLError):
                time.sleep(.1)
        else:
            pytest.fail('isolated Vite fixture did not become ready')
        yield url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


@pytest.fixture
def page(fixture_url):
    pytest.importorskip('playwright.sync_api')
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as error:
            pytest.skip(f'isolated Chromium unavailable: {type(error).__name__}')
        try:
            page = browser.new_page(viewport={'width': 1100, 'height': 800})
            # Neither local Canvas nor a real LAN listener receives these calls.
            page.add_init_script('''
              window.mobileFixture = {available:false, starts:0, statusCalls:0,
                                      failFirstStart:true, delaySecondStatus:false};
              window.fetch = async (path,options={}) => {
                if (new URL(path,location.href).pathname !== '/api/mobile/control')
                  throw new Error('unexpected fixture request');
                const f=window.mobileFixture, body=JSON.parse(options.body);
                if (body.action==='list') return Response.json({value:[]});
                if (body.action==='status') {
                  const captured=f.available; f.statusCalls++;
                  if (f.delaySecondStatus && f.statusCalls===2)
                    await new Promise(resolve=>setTimeout(resolve,1600));
                  return Response.json({value:{available:captured,status:captured?'ready':'unavailable',lan:captured,reason:'Estado de teste'}});
                }
                if (body.action==='start') {
                  f.starts++;
                  if (f.failFirstStart && f.starts===1)
                    return Response.json({error:'A porta de teste está ocupada.'},{status:503});
                  f.available=true; return Response.json({value:{started:true}});
                }
                throw new Error('unexpected fixture action');
              };
            ''')
            page.goto(fixture_url)
            page.get_by_role('button', name='Ativar conexão LAN / VPN').wait_for()
            page.wait_for_function('window.mobileFixture.statusCalls >= 1')
            yield page
        finally:
            browser.close()


def test_action_error_survives_successful_status_poll_until_new_action(page):
    page.get_by_role('button', name='Ativar conexão LAN / VPN').click()
    error = page.get_by_role('alert').filter(has_text='A porta de teste está ocupada.')
    error.wait_for()
    page.wait_for_function('window.mobileFixture.statusCalls >= 2', timeout=6000)
    assert error.is_visible()
    assert page.evaluate('window.mobileFixture.starts') == 1
    page.get_by_role('button', name='Ativar conexão LAN / VPN').click()
    page.get_by_text('Gateway conectado').wait_for()
    assert error.count() == 0
    assert page.evaluate('window.mobileFixture.starts') == 2


def test_late_poll_does_not_undo_new_gateway_status(page):
    page.evaluate('window.mobileFixture.failFirstStart=false; window.mobileFixture.delaySecondStatus=true')
    page.wait_for_function('window.mobileFixture.statusCalls >= 2', timeout=6000)
    page.get_by_role('button', name='Ativar conexão LAN / VPN').click()
    page.get_by_text('Gateway conectado').wait_for()
    page.wait_for_timeout(1800)
    assert page.get_by_text('Gateway conectado').is_visible()
    assert page.evaluate('window.mobileFixture.starts') == 1


@pytest.mark.parametrize('theme,width', [('dark', 1100), ('light', 430)])
def test_dialog_stays_keyboard_accessible_and_within_viewport(page, theme, width, tmp_path):
    page.set_viewport_size({'width': width, 'height': 800})
    page.evaluate('(theme) => document.documentElement.dataset.sentraTheme=theme', theme)
    dialog = page.get_by_role('dialog', name='Conectar Android ou iPhone')
    assert dialog.is_visible()
    page.get_by_text('Gateway indisponível').wait_for(timeout=6000)
    button = page.get_by_role('button', name='Ativar conexão LAN / VPN')
    button.focus()
    assert button.evaluate('(element) => document.activeElement === element')
    box = dialog.bounding_box()
    assert box and box['x'] >= -1 and box['x'] + box['width'] <= width + 1
    page.screenshot(path=str(tmp_path / f'pairing-{theme}-{width}.png'))
