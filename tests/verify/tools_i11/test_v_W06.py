"""V W06: the catalog of checks carries the VERSION and CONDITIONS of a result, so it cannot be ascribed to another build / set / device. A stage of the register that is ``yes`` through a green test run
must name the build (``sha``) and the conditions (``conditions``) of that run. A tool test on the real backlog_register.stages; not run on the laptop."""
from tools import backlog_register as br


def test_verified_stage_carries_the_build_and_conditions_of_the_run():
    files = ['echo_sync/instant.py', 'tests/test_instant.py']
    st = br.stages('N999', br.DONE, files, {'tests/test_instant.py': True})
    verified = st['verified_shared']
    assert verified['v'] == br.YES, verified                      # the base: the green run is read
    assert verified.get('sha'), 'a verified result without the build it was made on: %s' % verified
    assert verified.get('conditions'), 'a verified result without the conditions (set, device, load): %s' % verified
