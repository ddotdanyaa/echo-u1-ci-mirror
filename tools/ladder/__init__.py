"""G1: the ladder. Six levels of scenes on the stand, each level 200 scenes of different seeds; a level counts only at a hundred of a hundred.

  L0 one clean question in silence, its answer from the bank (or the material rows of the bank)       L1 five questions in a row with pauses
  L2 L1 and the owner repeats the cue and stumbles                                                     L3 L2 and long preambles, questions with a condition
  L4 L3 and noise, other people's speech                                                               L5 L4 and a flood of questions, a dropped link, barge-in

The scene is ``tools.rehearsal.sim.Rehearsal`` (the real ControlledMedia, NativeMediaSocket, ShadowEar, FastText; the candidate's flags on) driven by a script
instead of weights: what is asked, when, what the owner repeats. The bank is the real one (``cloud_context/bank/merged``) behind the controller's ``instant``;
the fake model answers from the same truth. A scene passes when every question owed an answer got a cue that fits it, and nothing else went wrong (``verdict``).
Seconds are the stand's, not a laptop's or a phone's.
"""
