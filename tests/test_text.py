from custom_components.somtoday.text import plain_text


def test_exam_html_becomes_readable_numbered_notes():
    assert plain_text('<p>Leren Hoofdstuk 1 </p><ol><li>lezen</li><li>grammatica '
                      'zinsdelen</li><li>spelling woordenboek</li></ol>'
                      '<p>Formuleren zinnen &amp; leestekens</p>') == (
        'Leren Hoofdstuk 1\n1. lezen\n2. grammatica zinsdelen\n'
        '3. spelling woordenboek\nFormuleren zinnen & leestekens')


def test_plain_text_paragraphs_and_repeated_normalization_are_preserved():
    value = 'Room 211\n\nHuiswerk\n• Exercises — Openstaand'
    assert plain_text(value) == value
    assert plain_text(plain_text('<p>Leer dit</p><ul><li>A</li></ul>')) == 'Leer dit\n• A'


def test_no_script_style_or_comments_leak_into_notes():
    assert plain_text('<p>Lees <b>hoofdstuk 1</b></p><!-- internal -->'
                      '<script>secret</script><style>hidden</style><p>Einde</p>') == 'Lees hoofdstuk 1\nEinde'
