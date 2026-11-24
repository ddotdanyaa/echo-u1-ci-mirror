"""I2 (E05, E05.1, U132, U133, W11, E52, U28): the table of stages over an archive of calls (``tools.call_report.stage_table``): the stages add up to the interval, a search is told from no search,
the passport of the contract (section 6) and the server-layer label are there, no reply text leaks, and the stand's pause assumption is compared with the journals (``hold_sweep.real_pauses``)."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
import call_report as R  # noqa: E402

SECRET = 'СЕКРЕТНАЯ-РЕПЛИКА'


def _call(t0, search=False, source='phone', flags='f1'):
    """One answer: the ear cut at t0, ear text 100 ms later, a job (start, first text), the decision, synthesis, the first PCM."""
    rows = [{'t': 0, 'ev': 'call_open', 'wall': '2026-11-13T12:00:00+03:00', 'source': source, 'build': 'b1', 'flags': flags, 'policy': 'p'}]
    rows.append({'t': t0 + 100, 'ev': 'ear_final', 'text': SECRET, 'kind': 'question', 'reason': 'question_word', 'lag_ms': 100})
    rows.append({'t': t0 + 400, 'ev': 'fast_adopted', 'job': 1, 'on': 'ear', 'ms': 300, 'ready_ms': 100})
    rows.append({'t': t0 + 450, 'ev': 'fast_job', 'job': 1, 'on': 'ear', 'ttft_ms': 200, 'outcome': 'ok', 'reason': '-', 'released': 1, 'adopted': 1, 'total_tokens': 50})
    rows.append({'t': t0 + 500, 'ev': 'decision', 'kind': 'lookup' if search else 'question', 'reason': 'sources_ok' if search else 'ear_first'})
    rows.append({'t': t0 + 600, 'ev': 'stage', 'name': 'synthesis_start'})
    rows.append({'t': t0 + 700, 'ev': 'stage', 'name': 'synthesis_end'})
    rows.append({'t': t0 + 800, 'ev': 'cue_end', 'status': 'completed', 'first_ms': t0 + 750, 'last_ms': t0 + 3000, 'text': SECRET})
    rows.append({'t': t0 + 9000, 'ev': 'call_close', 'elapsed_ms': t0 + 9000})
    return rows


def _write(folder, name, rows):
    (folder / name).write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in rows) + '\n', encoding='utf-8')


def test_stages_add_up_search_is_told_from_no_search_and_the_passport_is_there(tmp_path):
    _write(tmp_path, '20261113-100000-a.jsonl', _call(1000, search=False))
    _write(tmp_path, '20261113-100100-b.jsonl', _call(2000, search=True))
    _write(tmp_path, '20261113-100200-c.jsonl', _call(1000, source='probe'))      # a probe never enters the table
    (tmp_path / '20261113-100000-a.v5tap.jsonl').write_text('{"t":1,"ev":"mic"}\n')
    out = R.stage_table(tmp_path)
    assert out['paths']['no_search']['episodes'] == 1 and out['paths']['search']['episodes'] == 1
    for label in ('search', 'no_search'):
        table = out['paths'][label]
        assert table['total_ms']['median'] == 750 - 0                              # ear cut (t0) to the first PCM, from the journal's clock
        assert sum(s['median'] for s in table['stages'].values()) == table['total_ms']['median']
    assert out['paths']['search']['stages']['search']['n'] == 1 and 'search' not in out['paths']['no_search']['stages']
    assert out['checks']['sum_within_10pct'] == 2
    p = out['passport']
    assert p['set'].startswith('echo_calls') and '@' in p['checker'] and 'phone calls' in p['n_of_N'] and 'NOT measured' in p['layer']
    assert out['jobs']['tokens']['total_tokens'] == 100 and out['jobs']['queue_depth'] == 'not in the journal'


def test_the_report_holds_no_reply_text_and_says_the_server_layer(tmp_path):
    _write(tmp_path, '20261113-100000-a.jsonl', _call(1000))
    text = R.stage_markdown(R.stage_table(tmp_path)) + json.dumps(R.stage_table(tmp_path), ensure_ascii=False)
    assert SECRET not in text and 'серверный' in text and 'U133' in text


def test_a_folder_without_calls_gives_an_empty_table_not_a_crash(tmp_path):
    (tmp_path / 'x.jsonl').write_text('not json\n')
    out = R.stage_table(tmp_path)
    assert out['paths']['search']['episodes'] == 0 and out['checks']['enough_for_u133'] is False


def test_the_real_pause_law_is_read_from_the_journals(tmp_path):
    from tools.replay import hold_sweep as H
    rows = [{'t': i, 'ev': 'ear_final', 'text': 'x', 'onset_input_ms': on, 'offset_input_ms': off} for i, (on, off) in enumerate([(0, 1000), (1800, 2500), (4000, 5000)])]
    _write(tmp_path, '20261113-100000-a.jsonl', rows)
    law = H.real_pauses(tmp_path)
    assert law['n'] == 2 and law['p50'] == 1.5 and law['calls'] == 1 and 'server layer' in law['layer']
