"""The microphone of a stand: the phone streams a packet of 0.1 s every 0.1 s all call long.

Since ed34c63f (the owner's profile is the rule of every call) the input meter is the repeat gate of every call: with no packet for a second (a lost line), in the
first 20 packets (warming) or with digital zero for 2 s the silence timer holds its repeat. A stand that streams nothing never hears a timer of the product, so the stand
has to be a live line. ``LiveLine.run_to(now)`` gives the controller the packets the phone would have sent up to ``now``: the meter is NOT replaced or relaxed, it reads
a line that is there. A test that feeds its own packets (or none: a lost line) switches the stream of the world off with ``World.mic_stream = False``.
"""
PACKET_S = 0.1
BYTES_PER_S = 48000      # as call_trace.PCM_BYTES_PER_SECOND: 24 kHz, 16 bit, mono
LINE_DBFS = -30.0      # a line with sound on it, far above the digital zero of the meter (-90 dBFS)


class LiveLine:
    def __init__(self, controller, start, dbfs=LINE_DBFS):
        self.controller, self.at, self.dbfs = controller, float(start), dbfs

    def run_to(self, now):
        """The packets the phone has sent between the last one and ``now``, each stamped with the time it would have come at."""
        while self.at + PACKET_S <= now + 1e-9:
            self.at += PACKET_S
            self.controller.mic_packet(int(PACKET_S * BYTES_PER_S), self.dbfs, now=self.at)

    def attach(self):
        """Every look of the controller (``tick``) is preceded by the line up to that moment, whatever the stand's clock did before it (a jump of 30 s included)."""
        tick = self.controller.tick

        def live_tick(*, now):
            if now is not None:
                self.run_to(now)
            return tick(now=now)

        self.controller.tick = live_tick
        return self
