"""Literal bracket prose survives; structured tool arguments never paint."""
import pytest
from sentra_core.model_prose import prose_prefix


@pytest.mark.parametrize('text',[
    'Unicode 🪐 [[wiki]] repeated [[wiki]] final',
    '[[ação 🪐]] [[Canvas]] [[cANVAS]] [[wiki|literal]]',
    '[[[[wiki]]]] [array] [1,2] [ [] ]',
    'prefix [[UPPER text is not a directive]] end',
])
def test_legitimate_brackets_survive_incremental_and_complete_projection(text):
    assert prose_prefix(text)==text
    previous=''
    for index in range(1,len(text)+1):
        current=prose_prefix(text[:index])
        assert current.startswith(previous)
        previous=current
    assert prose_prefix(text,complete=True)==text


@pytest.mark.parametrize('marker',[
    '[[CANVAS|machine_execute|{"secret":"never paint"}]]',
    '[[MEMORY|search|internal context]]',
    '[[R|private/path]]', '[[STATUS]]', '[[FUTURE_TOOL|never paint]]',
    '[[CANVAS|unfinished secret',
])
def test_structured_headers_and_split_prefixes_never_emit_tool_arguments(marker):
    text='Visible [[wiki]] 🪐 '+marker+' later text'
    prefix='Visible [[wiki]] 🪐 '
    prior=''
    for index in range(1,len(text)+1):
        current=prose_prefix(text[:index])
        assert current.startswith(prior)
        assert current==prefix[:len(current)]
        prior=current
    assert prose_prefix(text)==prefix
    assert prose_prefix(text,complete=True)==prefix


@pytest.mark.parametrize('tail',['[','[[','[[CAN','[[CANVAS]'])
def test_ambiguous_prefix_can_resolve_as_literal_without_losing_bytes(tail):
    assert prose_prefix('prefix '+tail)=='prefix '
    assert prose_prefix('prefix '+tail,complete=True)=='prefix '+tail


def test_unambiguous_lowercase_is_not_delayed_until_generation_completes():
    assert prose_prefix('prefix [[wi')=='prefix [[wi'
    assert prose_prefix('prefix [[Canvas')=='prefix [[Canvas'
