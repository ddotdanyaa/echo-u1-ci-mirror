"""U17-S3: the pure InputMeter. One state per listening window and the repeat action read from it; no clock of its own (every call is given ``now``)."""
import unittest

from echo_sync import call_trace, input_state, timer_policy
from echo_sync.input_state import InputMeter


def fed(meter, start, seconds, dbfs=-30.0, step=0.1):
    """Packets of ``step`` seconds from ``start`` for ``seconds``; returns the time after the last one."""
    t = start
    end = start + seconds
    while t < end - 1e-9:
        t += step
        meter.packet(t, int(step * call_trace.PCM_BYTES_PER_SECOND), dbfs)
    return t


class StateTable(unittest.TestCase):
    def test_thresholds_come_from_call_trace(self):
        self.assertIs(input_state.DUPLEX_MIN_PACKETS, call_trace.DUPLEX_MIN_PACKETS)
        self.assertIs(input_state.DUPLEX_MIN_CUE_S, call_trace.DUPLEX_MIN_CUE_S)

    def test_warming_then_no_packets(self):
        m = InputMeter(0.0)
        self.assertEqual(m.state(0.5), 'warming')
        self.assertEqual(m.state(input_state.NO_PACKET_GAP_S + 0.1), 'no_packets')

    def test_warming_until_enough_packets_then_silence(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 1.0)
        self.assertEqual(m.state(t), 'warming')            # 10 packets
        t = fed(m, t, 1.0)
        self.assertEqual(m.state(t), 'silence')            # 20 packets

    def test_gap_of_1_5_s_is_no_packets(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        self.assertEqual(m.state(t + 0.5), 'silence')
        self.assertEqual(m.state(t + 1.5), 'no_packets')
        t2 = fed(m, t + 1.5, 0.2)
        self.assertEqual(m.state(t2), 'silence')

    def test_dead_input(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 1.0, dbfs=-30.0)
        t = fed(m, t, input_state.DEAD_INPUT_S - 0.5, dbfs=-96.0)
        self.assertEqual(m.state(t), 'silence')
        t = fed(m, t, 1.0, dbfs=-96.0)
        self.assertEqual(m.state(t), 'dead_input')
        t = fed(m, t, 0.2, dbfs=-30.0)
        self.assertEqual(m.state(t), 'silence')

    def test_asr_fault(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.fault(t, 'ear_down')
        self.assertEqual(m.state(t + 0.1), 'asr_fault')
        m.reset(t + 0.2)
        self.assertEqual(m.state(t + 0.3), 'silence')

    def test_heard_wins_over_unconfirmed_voice(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.vad(t, 800)
        m.ear(t + 0.2, 'hello there')
        self.assertEqual(m.state(t + 0.3), 'heard')
        t = fed(m, t, 6.0)
        m.reset(t)
        self.assertEqual(m.state(t + 0.1), 'silence')

    def test_cloud_text_is_heard(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.cloud(t, True)
        self.assertEqual(m.state(t), 'heard')

    def test_quiet_speech(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0, dbfs=-60.0)
        m.vad(t, 600)
        t = fed(m, t, input_state.ASR_GRACE_S + 0.2, dbfs=-60.0)
        self.assertEqual(m.state(t), 'quiet_speech')

    def test_short_voice_is_not_speech(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.vad(t, input_state.MIN_SPEECH_MS - 100)
        t = fed(m, t, 5.0)
        self.assertEqual(m.state(t), 'silence')

    def test_1602_pending_then_unintelligible(self):
        """07.11 16:02: the ear heard 2021 ms of speech and gave an empty final."""
        m = InputMeter(0.0)
        t = fed(m, 0.0, 47.0)
        m.vad(t, 2021)
        m.ear(t + 0.3, '', 'empty', 2021)
        self.assertEqual(m.state(t + 0.3), 'pending_asr')
        t1 = fed(m, t, 0.3 + input_state.ASR_GRACE_S - 0.2)
        self.assertEqual(m.state(t1), 'pending_asr')
        t2 = fed(m, t1, 0.4)
        self.assertEqual(m.state(t2), 'unintelligible')

    def test_ear_other_language_is_pending_until_the_hold_ends(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 10.0)
        hold = 8.0
        m.ear(t, '', 'ear_other_language', 1500, hold_s=hold)
        t1 = fed(m, t, input_state.ASR_GRACE_S + 1.0)
        self.assertEqual(m.state(t1), 'pending_asr')
        t2 = fed(m, t1, hold - 0.1 - (t1 - t))
        self.assertEqual(m.state(t2), 'pending_asr')
        self.assertEqual(m.repeat_action(t2).act, 'hold')
        t3 = fed(m, t2, 0.3)
        self.assertEqual(m.state(t3), 'unintelligible')

    def test_grace_is_inside_the_language_hold(self):
        self.assertEqual([k for k in timer_policy.unregistered() if k.startswith('input_state.')], [])
        self.assertEqual(timer_policy.validate({'asr_grace_seconds': input_state.ASR_GRACE_S}), [])


class RepeatAction(unittest.TestCase):
    def test_holds_without_input_or_ear(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        self.assertEqual(m.repeat_action(t).act, 'repeat')                     # silence, duplex unknown
        self.assertEqual(m.repeat_action(t + 2.0).act, 'hold')                 # no packets
        self.assertEqual(InputMeter(0.0).repeat_action(0.2).act, 'hold')       # warming

    def test_unintelligible_is_unconfirmed(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.vad(t, 1500)
        self.assertEqual(m.repeat_action(t + 0.2).act, 'hold')                 # pending
        t = fed(m, t, input_state.ASR_GRACE_S + 0.3)
        a = m.repeat_action(t)
        self.assertEqual((a.act, a.state), ('unconfirmed', 'unintelligible'))

    def test_heard_repeats(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.ear(t, 'text')
        self.assertEqual(m.repeat_action(t).act, 'repeat')

    def _half(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.cue_begin(t)
        end = t + 3.0                      # nothing arrives while the cue plays: the phone drops the mic
        m.cue_end(end)
        return m, end

    def test_half_duplex_defers_at_1_5_and_repeats_at_2_0(self):
        m, end = self._half()
        t = fed(m, end, 1.5)
        self.assertEqual(m.duplex(t), 'half')
        a = m.repeat_action(t)
        self.assertEqual((a.act, a.state), ('defer', 'silence'))
        self.assertAlmostEqual(a.got_s, 1.5, places=2)
        t = fed(m, t, 0.5)
        a = m.repeat_action(t)
        self.assertEqual(a.act, 'repeat')
        self.assertAlmostEqual(a.got_s, 2.0, places=2)

    def test_half_duplex_cue_gap_is_not_no_packets(self):
        m, end = self._half()
        self.assertEqual(m.state(end + 0.5), 'silence')

    def test_full_duplex_does_not_defer(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 1.0)
        m.cue_begin(t)
        t = fed(m, t, 3.0)
        m.cue_end(t)
        self.assertEqual(m.duplex(t), 'full')
        self.assertEqual(m.repeat_action(t + 0.05).act, 'repeat')

    def test_summary_is_numbers_and_labels_only(self):
        m = InputMeter(0.0)
        t = fed(m, 0.0, 3.0)
        m.state(t)
        m.vad(t, 1500)
        t = fed(m, t, 3.0)
        m.state(t)
        s = m.summary(t)
        self.assertEqual(s['packets'], 60)
        self.assertEqual(s['state'], 'unintelligible')
        self.assertGreaterEqual(s['states']['unintelligible'], 1)


if __name__ == '__main__':
    unittest.main()
