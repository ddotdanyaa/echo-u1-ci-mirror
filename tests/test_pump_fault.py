"""Level 1 of 06.11: one TypeError in the job pump at question 17 switched the job channel off for the other 13 questions of the call. A fault costs its job, three of them the channel."""
import asyncio
import types

from echo_sync import native_media_socket as M


class Job:
    released = {'turn': 't1'}


class Fast:
    def __init__(self):
        self.off, self.job, self.finished = False, Job(), []

    def poll(self):
        return [{'turn': 't1', 'qid': 'q', 'kind': 'text', 'text': 'x'}]

    def finish(self, turn):
        self.finished.append(turn)

    def shutdown(self):
        self.off = True


class Controller:
    def __init__(self):
        self.lost = []

    def fast_feed(self, *_):
        raise TypeError('of the controller')

    def fast_job_lost(self):
        self.lost.append('job')
        return []

    def fast_lost(self):
        self.lost.append('all')
        return []


def wire():
    async def nothing(*_):
        return None
    socket = types.SimpleNamespace(fast=Fast(), controller=Controller(), _fast_pumping=False, actions=nothing)
    socket._fast_hand_back = types.MethodType(M.NativeMediaSocket._fast_hand_back, socket)
    return socket


def test_one_fault_costs_its_job_and_the_channel_stays():
    socket = wire()
    asyncio.run(M.NativeMediaSocket._fast_pump(socket))
    assert not socket.fast.off and socket.fast.finished == ['t1'] and socket.controller.lost == ['job']


def test_the_third_fault_switches_the_channel_off():
    socket = wire()
    for _ in range(M.FAST_FAULTS):
        asyncio.run(M.NativeMediaSocket._fast_pump(socket))
    assert socket.fast.off and socket.controller.lost[-1] == 'all'
