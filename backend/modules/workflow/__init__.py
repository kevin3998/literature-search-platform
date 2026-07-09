"""Block 7/10: Deep Research Task Engine — native workflow runs.

A workflow run is an ordered sequence of steps; each step binds to an in-process
``runner``. P1 ships only the ``corpus-stage`` runner, which wraps the underlying
``ResearchRunManager`` (already a checkpointed multi-stage pipeline) so the run's
sub-stages render as a live timeline and resume-from-failed-stage works for free.
Later phases add an ``agent-step`` runner over the platform's own AgentLoop.
"""
