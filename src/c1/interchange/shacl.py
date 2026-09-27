"""Structural SHACL validation against trusted, bundled profile shapes."""

from __future__ import annotations

from pyshacl import validate
from rdflib import Graph
from rdflib.namespace import RDF, SH

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
    if isinstance(report, Graph):
        for result in report.subjects(RDF.type, SH.ValidationResult):
            focus = next(report.objects(result, SH.focusNode), None)
            path = next(report.objects(result, SH.resultPath), None)
            message = next(report.objects(result, SH.resultMessage), None)
            diagnostics.append(
                Diagnostic(
                    code="C1-IX-030",
                    severity="error",
                    path=f"{focus or ''} {path or ''}".strip(),
                    message=str(message or "Record violates profile structure"),
                )
            )
    if not diagnostics:
        diagnostics.append(
            Diagnostic(
                code="C1-IX-030",
                severity="error",
                path="",
                message="Record violates bundled SHACL shapes",
            )
        )
    raise ProfileError(diagnostics)
