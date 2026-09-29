"""Structural SHACL validation against trusted, bundled profile shapes."""

from __future__ import annotations

from pyshacl import validate
from rdflib import Graph, URIRef
from rdflib.namespace import RDF, SH
from rdflib.term import Node

from c1.model.diagnostics import Diagnostic, ProfileError
from c1.model.profiles import ProfileRegistry


def validate_shacl(graph: Graph, registry: ProfileRegistry) -> None:
    conforms, report, _text = validate(
        graph,
        shacl_graph=registry.shapes,
        inference="none",
        advanced=False,
        js=False,
        do_owl_imports=False,
        meta_shacl=False,
    )
    if conforms:
        return
    diagnostics: list[Diagnostic] = []
    skipped = 0
    if isinstance(report, Graph):
        for result in report.subjects(RDF.type, SH.ValidationResult):
            focus = next(report.objects(result, SH.focusNode), None)
            path = next(report.objects(result, SH.resultPath), None)
            message = next(report.objects(result, SH.resultMessage), None)
            if _external_class_reference(report, result, graph, registry):
                skipped += 1
                continue
            diagnostics.append(
                Diagnostic(
                    code="C1-IX-030",
                    severity="error",
                    path=f"{focus or ''} {path or ''}".strip(),
                    message=str(message or "Record violates profile structure"),
                )
            )
    if not diagnostics:
        if skipped:
            return
        diagnostics.append(
            Diagnostic(
                code="C1-IX-030",
                severity="error",
                path="",
                message="Record violates bundled SHACL shapes",
            )
        )
    raise ProfileError(diagnostics)


def _external_class_reference(
    report: Graph, result: Node, graph: Graph, registry: ProfileRegistry
) -> bool:
    """A class constraint on a reference outside the validated batch is not a record defect.

    SHACL can only see the records being validated. A class-ranged reference to
    an existing record is checked against that record's actual types by
    ChangeSet validation and apply (C1-CS-010/C1-CS-013) instead.
    """
    component = next(report.objects(result, SH.sourceConstraintComponent), None)
    if component not in {SH.ClassConstraintComponent, SH.OrConstraintComponent}:
        return False
    value = next(report.objects(result, SH.value), None)
    path = next(report.objects(result, SH.resultPath), None)
    if not isinstance(value, URIRef) or not isinstance(path, URIRef):
        return False
    if next(graph.objects(value, RDF.type), None) is not None:
        return False
    definition = registry.predicates.get(str(path))
    return (
        definition is not None
        and bool(definition.ranges)
        and all(item in registry.classes for item in definition.ranges)
    )
