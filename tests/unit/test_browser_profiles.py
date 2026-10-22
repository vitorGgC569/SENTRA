import json
import sqlite3
import pytest
from sentra_executors.browser_profiles import BrowserProfiles
from sentra_executors.playwright_browser import NetworkProfile


def scope(machine='machine',principal='dot',capability='browser:operate',work='work'):
    return json.dumps([machine,principal,capability,work])


def test_protected_login_survives_workitem_change_but_not_owner_machine_or_binding(tmp_path):
    store=BrowserProfiles(tmp_path)
    state={'cookies':[],'origins':[{'origin':'http://127.0.0.1:9000','localStorage':[{'name':'fixture','value':'PRIVATE-LOGIN-FIXTURE'}]}]}
    store.save(scope(),'binding','profile',state)
    assert BrowserProfiles(tmp_path).load(scope(work='next-authorized-work'),'binding','profile')==state
    for other in [scope(machine='other'),scope(principal='other'),scope(capability='other')]:
        assert store.load(other,'binding','profile') is None
    assert store.load(scope(),'other-binding','profile') is None
    assert store.load(scope(),'binding','other-profile') is None
    assert b'PRIVATE-LOGIN-FIXTURE' not in store.path.read_bytes()
    store.forget(scope(),'binding','profile')
    assert store.load(scope(),'binding','profile') is None


def test_login_corruption_and_future_schema_fail_without_replacement(tmp_path):
    store=BrowserProfiles(tmp_path)
    with sqlite3.connect(store.path) as db:
        db.execute('INSERT INTO logins VALUES(?,?,0)',(store.identity(scope(),'binding','profile'),'damaged'))
    with pytest.raises((RuntimeError,ValueError,PermissionError)):
        store.load(scope(),'binding','profile')
    with sqlite3.connect(store.path) as db:db.execute('PRAGMA user_version=99')
    with pytest.raises(ValueError,match='newer'):BrowserProfiles(tmp_path)


def test_profile_persistence_requires_explicit_boolean_and_bounded_state(tmp_path):
    assert NetworkProfile('offline').remember_login is False
    with pytest.raises(ValueError):NetworkProfile('bad',remember_login='yes')
    store=BrowserProfiles(tmp_path)
    with pytest.raises(ValueError):store.save(scope(),'b','p',{'passwords':'not-storage-state'})
    with pytest.raises(ValueError):store.identity('client-supplied-scope','b','p')
