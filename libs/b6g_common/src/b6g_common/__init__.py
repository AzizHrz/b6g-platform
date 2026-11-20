"""Bibliothèque partagée B6G (M00), contrats 1.0.0.

API publique :
    scenario.load()             -> dict (I-01 validé)
    snapshot.build(prom_url)    -> MetricSnapshot (I-03)
    validate(obj, "nom")        -> lève ContractError si invalide
    events.make(...)            -> événement b6g.event.v1 (I-08)
    actions.check(...)          -> contrôle sémantique d'un ActionRequest (I-04)
"""
from . import actions, events, scenario, snapshot
from .schemas import ContractError, errors, validate
from .timeutil import now_iso

__version__ = "1.0.0"
CONTRACTS_VERSION = "1.0.0"
__all__ = ["actions", "events", "scenario", "snapshot", "validate", "errors", "ContractError", "now_iso",
           "CONTRACTS_VERSION"]
