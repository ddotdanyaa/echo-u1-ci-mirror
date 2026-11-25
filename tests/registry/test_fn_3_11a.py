"""3.11a: материал и подбор его частей под вопрос. Модели уходят части материала, подходящие вопросу, а не первые 12 000 знаков."""
import _h3 as H

TOPICS = ['Вулканы острова Тирра', 'Приливы бухты Ломар', 'Сорта сыра фирмы Алмас', 'Спутники планеты Гелиос']
QUESTION = 'Сколько спутников у планеты Гелиос?'
FACT = 'У планеты Гелиос одиннадцать спутников, самый крупный зовётся Орвин.'


def make_material():
    """Четыре темы по ~7 000 знаков; нужный факт только в последней: он лежит за первыми 12 000 знаками."""
    parts = []
    for n, topic in enumerate(TOPICS):
        fill = ' '.join('Запись %d о теме «%s»: наблюдение номер %d сделано в сезон %d.' % (k, topic, k * 7 + n, k % 5) for k in range(95))
        parts.append('# %s\n\n%s%s' % (topic, FACT + ' ' if n == 3 else '', fill))
    return '\n\n'.join(parts)


def sent_material(tmp_path, monkeypatch, question=QUESTION):
    """Что увидела модель в инструкции запроса на вопрос, при материале в файле context.md."""
    model = H.Model({'гелиос': 'Одиннадцать.', 'тирра': 'Это остров.'})

    async def body(host):
        await H.say(host, question)
        await host.advance(2)
        return H.journal(host)

    rows = H.play(tmp_path, monkeypatch, body, model=model, files={'materials/context.md': make_material()})
    assert model.questions() == [question], model.questions()
    return model.requests[0].request['instructions'], rows


def test_the_model_sees_the_part_of_the_material_that_fits_the_question(tmp_path, monkeypatch):
    assert len(make_material()) > 25000
    text, _ = sent_material(tmp_path, monkeypatch)
    assert FACT in text, 'the fact lies beyond the first 12 000 chars of the material'
    assert 'Спутники планеты Гелиос' in text


def test_other_topics_do_not_crowd_out_the_picked_part(tmp_path, monkeypatch):
    text, _ = sent_material(tmp_path, monkeypatch)
    assert 'Запись 3 о теме «Сорта сыра фирмы Алмас»' not in text and 'Запись 3 о теме «Приливы бухты Ломар»' not in text
    assert len(text) < 9000, len(text)


def test_the_part_follows_the_next_question(tmp_path, monkeypatch):
    text, _ = sent_material(tmp_path, monkeypatch, 'Какие сорта сыра делает фирма Алмас?')
    assert 'Запись 3 о теме «Сорта сыра фирмы Алмас»' in text and FACT not in text


def test_subject_and_style_of_the_owner_reach_the_model_with_the_picked_part(tmp_path, monkeypatch):
    model = H.Model({'гелиос': 'Одиннадцать.'})

    async def body(host):
        await H.say(host, QUESTION)
        await host.advance(2)

    H.play(tmp_path, monkeypatch, body, model=model, files={'materials/context.md': make_material()},
           subject='астрономия, доклад про систему Гелиос', style='простыми словами, коротко')
    text = model.requests[0].request['instructions']
    assert 'астрономия, доклад про систему Гелиос' in text and 'простыми словами, коротко' in text
    assert FACT in text
