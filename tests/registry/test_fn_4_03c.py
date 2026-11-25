"""4.03c: text channel over a persistent socket (text_transport). Live profile: http. The network socket library is faked at its public seam (websockets.sync.client.connect);
the sign-in is given to the host's api stub (private name _codex_credentials: the host calls it, there is no public way). The HTTP model (H.Model) is the other road."""
import json, queue, sys, threading, types
import pytest
import _h4 as H

QUESTION = 'На каком материке находится озеро Эйр?'
SOCKET_ANSWER = 'Озеро Эйр лежит в Австралии. Оно часто бывает пересохшим.'
HTTP_ANSWER = 'Ответ пришёл по другой дороге.'


class Sock:
    """What websockets.sync.client.connect returns: send(text), recv(timeout), ping() -> Event, close()."""
    def __init__(self, net):
        self.net, self.inbox = net, queue.Queue()

    def send(self, text):
        frame = json.loads(text)
        self.net.frames.append(frame)
        if frame.get('generate') is False:
            self.inbox.put({'type': 'response.completed', 'response': {'id': 'w'}})
        else:
            for event in ({'type': 'response.created'}, {'type': 'response.output_text.delta', 'delta': self.net.answer(H.asked(frame))}, {'type': 'response.completed', 'response': {'id': 'r'}}):
                self.inbox.put(event)

    def recv(self, timeout=None):
        try: return json.dumps(self.inbox.get(timeout=timeout), ensure_ascii=False)
        except queue.Empty: raise TimeoutError('no frame') from None

    def ping(self):
        done = threading.Event()
        done.set()
        return done

    def close(self):
        pass


class Net:
    def __init__(self, answer):
        self.answer, self.frames, self.opened = answer, [], 0

    def connect(self, url, additional_headers=None, open_timeout=None, **_):
        self.opened += 1
        return Sock(self)

    def install(self, monkeypatch):
        names = ('websockets', 'websockets.sync', 'websockets.sync.client')
        modules = [types.ModuleType(n) for n in names]
        modules[2].connect = self.connect
        for name, module in zip(names, modules):
            monkeypatch.setitem(sys.modules, name, module)


def call(tmp_path, monkeypatch, **own):
    net, model = Net(lambda q: SOCKET_ANSWER if 'Эйр' in q else '—'), H.Model({'Эйр': HTTP_ANSWER})
    net.install(monkeypatch)

    async def body(host):
        host.api._codex_credentials = lambda: ('token-x', 'account-x')      # the sign-in the host reads for the text channel
        await H.say(host, QUESTION)
        await host.advance(3)
        return H.journal(host), host.spoken()
    rows, spoken = H.play(tmp_path, monkeypatch, body, model=model, **own)
    return net, model, rows, spoken


def check_answer_over_socket(net, model, rows, spoken):
    sent = [H.asked(f) for f in net.frames if f.get('generate') is not False and f.get('type') == 'response.create']
    assert sent == [QUESTION], 'the question went to the model over the socket: %r' % sent
    assert model.questions() == [], 'nothing went over HTTP: %r' % model.questions()
    assert spoken and 'Австрали' in spoken[0] and 'другой дороге' not in ' '.join(spoken), spoken
    assert ('answer', 'fast_text_owns') in H.decisions(rows)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason='реестр 4.03c: ВЫКЛЮЧЕНО, на сервере text_transport=http')
def test_b_target_the_model_answer_comes_over_the_socket_under_the_live_profile(tmp_path, monkeypatch):
    check_answer_over_socket(*call(tmp_path, monkeypatch))


def test_b_with_the_key_on_the_model_answer_comes_over_the_socket(tmp_path, monkeypatch):
    check_answer_over_socket(*call(tmp_path, monkeypatch, text_transport='ws'))


def test_b_control_under_the_live_profile_the_same_question_goes_over_http_and_no_socket_opens(tmp_path, monkeypatch):
    net, model, rows, spoken = call(tmp_path, monkeypatch)
    assert model.questions() == [QUESTION] and net.opened == 0 and net.frames == [], (model.questions(), net.opened)
    assert spoken and 'другой дороге' in spoken[0], spoken
    assert ('answer', 'fast_text_owns') in H.decisions(rows)
