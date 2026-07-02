"""CEDX agent fleet — roster + registry."""
from . import orchestrator, worker, verifier

ROSTER = [
    {
        "name": orchestrator.NAME,
        "role": orchestrator.ROLE,
        "models": orchestrator.MODELS,
        "prompt_version": orchestrator.PROMPT_VERSION,
        "can_call": orchestrator.CAN_CALL,
    },
    {
        "name": worker.NAME,
        "role": worker.ROLE,
        "models": worker.MODELS,
        "prompt_version": worker.PROMPT_VERSION,
        "can_call": worker.CAN_CALL,
    },
    {
        "name": verifier.NAME,
        "role": verifier.ROLE,
        "models": verifier.MODELS,
        "prompt_version": verifier.PROMPT_VERSION,
        "can_call": verifier.CAN_CALL,
    },
]

__all__ = ["orchestrator", "worker", "verifier", "ROSTER"]