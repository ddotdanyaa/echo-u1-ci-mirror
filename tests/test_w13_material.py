"""W13 item 7: the job's input. A material of 9 000 chars went whole into every request (12 300 in all): ``material_pick`` acted only when
the material was cut. With the flag on the job always gets the parts picked for the question, under 3 000 chars of material."""
import re
from pathlib import Path

import echo_sync
from echo_sync import material_pick as MP
from echo_sync.content_policy import CallContext

SUBJECTS = ['НДС', 'НДФЛ', 'страховые взносы', 'бухгалтерский баланс', 'основные средства', 'кассовая дисциплина']


def body():
    parts = []
    for n, subject in enumerate(SUBJECTS):
        parts.append(f'# {subject}\n' + ' '.join(f'Правило {k} про {subject}: срок {n * 10 + k} дней, ставка {k} процентов.' for k in range(22)))
    return '\n\n'.join(parts)


def test_the_job_gets_parts_of_a_material_that_fits_whole_in_the_old_cap():
    text = body()
    assert 6000 < len(text) < 12000, len(text)
    picker = MP.for_job(text)
    out, pick = picker.instructions_and_pick('Какой срок по страховым взносам?', (), CallContext(), 'POLICY')
    material = out.split('⟧', 1)[1].rsplit('⟦', 1)[0]
    assert len(material) < 3000 and pick.picked >= 1 and not pick.fallback, (len(material), pick)
    assert 'страховые взносы' in material and 'кассовая дисциплина' not in material


def test_the_host_picks_whenever_the_flag_is_on():
    host = (Path(echo_sync.__file__).parent / 'controlled_host.py').read_text(encoding='utf-8')
    line = next(line for line in host.splitlines() if "material_pick.for_job(" in line)
    assert 'truncated' not in line, line
    assert re.search(r'MaterialPicker|for_job', host) and 'material_pick.for_job(' in host or 'for_job(' in host
