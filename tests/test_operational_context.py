from herramientas.scanner_operativo_context import resolve_operational_scanner_context


def test_operational_context_resolves_active_scanner() -> None:
    context = resolve_operational_scanner_context()

    assert context.active_version >= 11
    assert context.active_scanner.name == "invertir_v13.py"
    assert context.active_learning is not None
    assert context.learning_chain

