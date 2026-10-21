"""Native form choices and protected resume IDs; no real account or Windows key."""
import json
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from sentra_remote import openai_auto_setup as auto
from sentra_remote import openai_browser_enrollment as en
from sentra_remote.product import ProductPaths


class Items:
    def __init__(self, items): self.items = items
    def count(self): return len(self.items)
    def nth(self, i): return self.items[i]
    def inner_text(self):
        assert len(self.items) == 1
        return self.items[0].inner_text()
    def is_visible(self): return len(self.items) == 1 and self.items[0].is_visible()
    def click(self, **kwargs):
        assert len(self.items) == 1
        self.items[0].click(**kwargs)
    def filter(self, *, visible): return Items([item for item in self.items if item.is_visible() == visible])


class Select:
    def __init__(self, labels, *, enabled=True):
        self.labels = labels
        self.selected = labels[0]
        self.enabled = enabled
        self.changes = []
    def locator(self, selector):
        labels = [self.selected] if selector == 'option:checked' else self.labels
        return Items([SimpleNamespace(inner_text=lambda label=label: label) for label in labels])
    def is_enabled(self): return self.enabled
    def select_option(self, *, label, timeout):
        assert self.enabled and self.labels.count(label) == 1
        self.changes.append(label)
        self.selected = label


def worker(selects):
    page = Mock(url=en.OPENAI_API_KEYS_URL)
    page.is_closed.return_value = False
    page.get_by_text.return_value.count.return_value = 0
    dialog = SimpleNamespace(locator=lambda selector: Items(selects))
    return auto.AutomaticEnrollment(page, Mock(), threading.Event()), dialog


def test_native_project_prefers_default_and_expiry_verifies_no_expiration():
    project = Select(['Select project...', 'Other project', 'Default project'])
    expiry = Select(['Selecione uma validade', '30 days', 'Never'])
    enrollment, dialog = worker([project, expiry])
    assert enrollment.select_native_project(dialog)
    assert project.changes == ['Default project']
    assert enrollment.select_native_expiry(dialog)
    assert expiry.changes == ['Never']
    assert auto.AutomaticEnrollment.native_selected_label(project) == 'Default project'
    assert auto.AutomaticEnrollment.native_selected_label(expiry) == 'Never'


def test_only_custom_project_is_selected_without_confusing_it_with_expiry():
    project = Select(['Selecionar projeto...', 'Never'])
    expiry = Select(['Expiração', 'Nunca', '30 dias'])
    enrollment, dialog = worker([project, expiry])
    assert enrollment.select_native_project(dialog)
    assert project.selected == 'Never'
    assert enrollment.select_native_expiry(dialog)
    assert expiry.selected == 'Nunca'


def test_multiple_custom_projects_wait_for_user_instead_of_choosing_one(monkeypatch):
    project = Select(['Select project...', 'Alpha', 'Beta'])
    enrollment, dialog = worker([project])
    original = enrollment.wait
    def wait(probe, **kwargs):
        if kwargs.get('timeout') == 600:
            project.selected = 'Beta'  # Synthetic user choice, no account action.
        return original(probe, **kwargs)
    monkeypatch.setattr(enrollment, 'wait', wait)
    assert enrollment.select_native_project(dialog)
    assert not project.changes
    assert project.selected == 'Beta'
    assert 'Choose the API key project' in enrollment.notify.call_args.args[1]


def test_multiple_expiry_controls_cannot_be_guessed():
    enrollment, dialog = worker([Select(['Expiration','Never']), Select(['Expiração','Nunca'])])
    with pytest.raises(ValueError, match='expiry_selection_required'):
        enrollment.select_native_expiry(dialog)


def test_hidden_or_custom_button_forms_are_left_to_the_existing_adapter():
    enrollment, dialog = worker([])
    assert enrollment.select_native_project(dialog) is False
    assert enrollment.select_native_expiry(dialog) is False


@pytest.fixture
def protected(monkeypatch):
    # Contract stand-in only. Actual DPAPI readiness is a normal-user integration check.
    stored = {}
    def protect(value):
        token = 'dpapi:synthetic-' + str(len(stored))
        stored[token] = value
        return token
    monkeypatch.setattr(auto, 'protect_secret', protect)
    monkeypatch.setattr(auto, 'unprotect_secret', lambda value: stored[value])
    return stored


def test_resume_checkpoint_is_install_bound_and_removed_only_for_its_own_id(tmp_path, protected):
    paths = ProductPaths(tmp_path/'install', tmp_path/'state')
    tunnel = 'tunnel_checkpoint0123456789'
    auto.remember_enrollment_tunnel(paths, tunnel)
    raw = (paths.state_dir/'openai-enrollment-tunnel.dpapi').read_text()
    assert tunnel not in raw
    assert auto.remembered_enrollment_tunnel(paths) == tunnel
    with pytest.raises(ValueError, match='manual_recovery_required'):
        auto.remembered_enrollment_tunnel(ProductPaths(tmp_path/'other', paths.state_dir))
    auto.clear_remembered_enrollment_tunnel(paths, 'tunnel_other0123456789')
    assert auto.remembered_enrollment_tunnel(paths) == tunnel
    auto.clear_remembered_enrollment_tunnel(paths, tunnel)
    assert auto.remembered_enrollment_tunnel(paths) == ''
    assert all('runtime_key' not in json.loads(value) for value in protected.values())


def test_corrupt_resume_checkpoint_stops_recovery_instead_of_silently_creating_again(tmp_path, protected):
    paths = ProductPaths(tmp_path/'install', tmp_path/'state')
    paths.state_dir.mkdir()
    (paths.state_dir/'openai-enrollment-tunnel.dpapi').write_text('bad')
    with pytest.raises(ValueError, match='manual_recovery_required'):
        auto.remembered_enrollment_tunnel(paths)


def test_saved_tunnel_missing_from_page_never_creates_a_replacement(monkeypatch):
    page = Mock(url=en.OPENAI_TUNNELS_URL)
    page.is_closed.return_value = False
    page.evaluate.return_value = ['tunnel_someother0123456789']
    enrollment = auto.AutomaticEnrollment(page, Mock(), threading.Event(),
        existing_tunnel_id='tunnel_previous0123456789')
    page.locator.return_value.count.return_value = 0
    def one_probe(probe, **kwargs):
        result = probe()
        if result is None:
            raise ValueError('platform_ui_needs_attention')
        return result
    monkeypatch.setattr(enrollment, 'wait', one_probe)
    with pytest.raises(ValueError, match='saved_tunnel_not_visible'):
        enrollment.run()
    page.click.assert_not_called()
    page.goto.assert_not_called()


def test_resume_opens_exact_protected_name_and_requires_matching_detail_id(monkeypatch):
    identifier = 'tunnel_previous0123456789'
    page = Mock(url=en.OPENAI_TUNNELS_URL)
    page.is_closed.return_value = False
    page.get_by_text.return_value.count.return_value = 0
    page.evaluate.side_effect = [[], [identifier]]
    page.locator.return_value.count.return_value = 0
    entry = page.get_by_role.return_value
    entry.count.return_value = 1
    entry.is_visible.return_value = True
    enrollment = auto.AutomaticEnrollment(page, Mock(), threading.Event(),
        existing_tunnel_id=identifier, existing_tunnel_name='SENTRA-1481f780cd')
    assert enrollment.select_existing_tunnel() == identifier
    entry.click.assert_called_once_with(timeout=5000)
    assert page.get_by_role.call_args.kwargs['name'].fullmatch('SENTRA-1481f780cd')
    assert not page.get_by_role.call_args.kwargs['name'].fullmatch('SENTRA-1481f780cd-copy')
    page.goto.assert_not_called()


def test_resume_wrong_detail_id_stops_before_key_navigation(monkeypatch):
    page = Mock(url=en.OPENAI_TUNNELS_URL)
    page.is_closed.return_value = False
    page.get_by_text.return_value.count.return_value = 0
    page.evaluate.return_value = ['tunnel_different0123456789']
    link = page.locator.return_value
    link.count.return_value = 1
    enrollment = auto.AutomaticEnrollment(page, Mock(), threading.Event(),
        existing_tunnel_id='tunnel_previous0123456789')
    def once(probe, **kwargs):
        result = probe()
        if result is None:
            raise ValueError('platform_ui_needs_attention')
        return result
    monkeypatch.setattr(enrollment, 'wait', once)
    with pytest.raises(ValueError, match='saved_tunnel_not_visible'):
        enrollment.run()
    link.click.assert_called_once()
    page.goto.assert_not_called()


def test_checkpoint_name_is_bound_to_identifier_and_rejects_arbitrary_labels(tmp_path, protected):
    paths = ProductPaths(tmp_path/'install', tmp_path/'state')
    identifier = 'tunnel_checkpoint0123456789'
    auto.remember_enrollment_tunnel(paths, identifier, name='SENTRA-1481f780cd')
    assert auto.remembered_enrollment_tunnel_name(paths, identifier) == 'SENTRA-1481f780cd'
    assert auto.remembered_enrollment_tunnel_name(paths, 'tunnel_other0123456789') == ''
    with pytest.raises(ValueError, match='saved_tunnel_not_visible'):
        auto.remember_enrollment_tunnel(paths, identifier, name='Unrelated account resource')


class CustomControl:
    def __init__(self, text, label, role='combobox', enabled=True):
        self.text, self.label, self.role, self.enabled = text, label, role, enabled
        self.clicks = 0
    def inner_text(self): return self.text
    def is_visible(self): return True
    def is_enabled(self): return self.enabled
    def click(self, **kwargs):
        assert self.enabled
        self.clicks += 1


def custom_dialog(controls):
    return SimpleNamespace(get_by_role=lambda role, name=None: Items([
        control for control in controls if control.role == role
        and (name is None or name.search(control.label))]))


def test_custom_combobox_uses_displayed_placeholder_despite_accessible_label():
    project = CustomControl('Select project...', 'Project')
    expiry = CustomControl('Selecione uma validade', 'Expiração', enabled=False)
    enrollment, _ = worker([])
    dialog = custom_dialog([project, expiry])
    assert enrollment.custom_key_control(dialog, 'project') is project
    assert enrollment.custom_key_control(dialog, 'expiry') is None
    expiry.enabled = True
    assert enrollment.custom_key_control(dialog, 'expiry') is expiry


def test_custom_selection_chooses_default_project_then_never_and_verifies_display():
    project = CustomControl('Select project...', 'Project')
    expiry = CustomControl('Selecione uma validade', 'Expiração', enabled=False)
    enrollment, _ = worker([])
    dialog = custom_dialog([project, expiry])
    default = CustomControl('Default project', '', role='option')
    never = CustomControl('Never', '', role='option')
    def choose_project(**kwargs):
        project.text = 'Default project'
        expiry.enabled = True
    default.click = choose_project
    never.click = lambda **kwargs: setattr(expiry, 'text', 'Never')
    enrollment.page.get_by_role.side_effect = lambda role, name=None: Items([
        item for item in ([never] if expiry.clicks else [default])
        if name is None or name.fullmatch(item.text)])
    enrollment.select_custom_project(dialog)
    assert project.text == 'Default project' and expiry.enabled
    enrollment.select_custom_expiry(dialog)
    assert expiry.text == 'Never' and expiry.clicks == 1


def test_custom_ambiguous_fields_are_not_clicked():
    enrollment, _ = worker([])
    controls = [CustomControl('Select project...', 'Project'), CustomControl('Select project...', 'Project')]
    with pytest.raises(ValueError, match='project_selection_required'):
        enrollment.select_custom_project(custom_dialog(controls))
    assert all(control.clicks == 0 for control in controls)


def test_custom_missing_field_blocks_key_creation_with_specific_reason(monkeypatch):
    enrollment, _ = worker([])
    def once(probe, **kwargs):
        if probe() is None:
            raise ValueError('platform_ui_needs_attention')
    monkeypatch.setattr(enrollment, 'wait', once)
    with pytest.raises(ValueError, match='expiry_selection_required'):
        enrollment.select_custom_expiry(custom_dialog([]))
    enrollment.page.goto.assert_not_called()


def test_extension_custom_selectors_use_fixed_pointer_action():
    control = Mock()
    auto.AutomaticEnrollment.click_custom_selector(control)
    control.pointer_click.assert_called_once_with(timeout=5000)
    control.click.assert_not_called()


def test_actual_combined_expiry_label_is_found_and_never_is_verified():
    expiry = CustomControl('Expiração Selecione uma validade', '', role='button')
    enrollment, _ = worker([])
    dialog = custom_dialog([expiry])
    assert enrollment.custom_key_control(dialog, 'expiry') is expiry
    option = CustomControl('Nunca', '', role='option')
    option.click = lambda **kwargs: setattr(expiry, 'text', 'Expiração Nunca')
    enrollment.page.get_by_role.side_effect = lambda role, name=None: Items([
        option] if role == 'option' and (name is None or name.fullmatch(option.text)) else [])
    enrollment.select_custom_expiry(dialog)
    assert expiry.text == 'Expiração Nunca'


@pytest.mark.parametrize('text,expected', [
    ('Expiração Nunca','Nunca'), ('Expiration: Never','Never'),
    ('Expiração\nSelecione uma validade','Selecione uma validade'),
    ('No expiration','No expiration'), ('Expiração 30 dias','30 dias'),
    ('Validade Sem expiração','Sem expiração')])
def test_expiry_normalization_preserves_the_actual_selected_value(text,expected):
    assert auto.AutomaticEnrollment.expiry_control_value(text) == expected
