import os
from pathlib import Path
import stat
from unittest.mock import Mock

import pytest

from sentra_remote.product_copy import copy_product_file


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only attribute')
def test_readonly_owned_license_is_replaced_without_mutating_source(tmp_path):
    root = tmp_path / 'installation'; root.mkdir()
    source, target = tmp_path / 'source', root / 'LICENSE'
    source.write_bytes(b'new license'); target.write_bytes(b'old license')
    os.chmod(source, stat.S_IREAD); os.chmod(target, stat.S_IREAD)
    try:
        copy_product_file(source, target, root=root)
        assert target.read_bytes() == source.read_bytes() == b'new license'
        assert target.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
        assert not list(root.glob('.sentra-copy-*'))
    finally:
        os.chmod(source, stat.S_IWRITE); os.chmod(target, stat.S_IWRITE)


def test_writable_permission_error_is_not_retried(tmp_path, monkeypatch):
    import sentra_remote.product_copy as module
    target = tmp_path / 'target'; target.write_bytes(b'old')
    copy = Mock(side_effect=PermissionError('locked executable'))
    monkeypatch.setattr(module.shutil, 'copy2', copy)
    with pytest.raises(PermissionError):
        copy_product_file(tmp_path / 'source', target, root=tmp_path)
    assert copy.call_count == 1 and target.read_bytes() == b'old'


@pytest.mark.skipif(os.name != 'nt', reason='Windows read-only attribute')
def test_failed_replacement_retains_original_content_and_attribute(tmp_path, monkeypatch):
    import sentra_remote.product_copy as module
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'new'); target.write_bytes(b'old')
    os.chmod(target, stat.S_IREAD)
    monkeypatch.setattr(module.os, 'replace', Mock(side_effect=PermissionError('locked')))
    try:
        with pytest.raises(PermissionError):
            copy_product_file(source, target, root=tmp_path)
        assert target.read_bytes() == b'old'
        assert target.stat().st_file_attributes & stat.FILE_ATTRIBUTE_READONLY
        assert not list(tmp_path.glob('.sentra-copy-*'))
    finally:
        os.chmod(target, stat.S_IWRITE)


def test_outside_destination_is_rejected_before_copy(tmp_path):
    root = tmp_path / 'owned'; root.mkdir()
    with pytest.raises(ValueError, match='escaped'):
        copy_product_file(tmp_path / 'source', tmp_path / 'outside', root=root)
    assert not (tmp_path / 'outside').exists()
