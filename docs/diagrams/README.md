# Comparison scope diagram

`comparison.html` is the editable, self-contained source. Its two SVGs have the
same meaning with layouts sized for a normal README and a narrow screen.
System fonts, explicit SVG styles and local arrow markers keep both standalone
exports readable without a web-font service, JavaScript or external assets.

After editing the HTML, regenerate the two README images:

```sh
python3 tools/export_diagrams.py
```

The exporter uses Python's standard library. It extracts only the two known SVG
elements, so the images keep their accessible titles/descriptions, fonts and
markers without depending on HTML wrapper CSS. The README's picture element
selects the narrow variant at 600 CSS pixels or less. Open either SVG directly
to inspect it at full size. The HTML preview uses the same breakpoint.

This is a conceptual diagram of `verify_ast` in
`src/native_recovery/recovery_core.py`, not a captured solver result or evidence
that an arbitrary binary was verified. The inputs are the supported instruction
model, editable expression and explicit domain. The SAT/UNSAT/UNKNOWN outcomes
retain the engine's distinct meanings. Unsupported input is refused before
this comparison; UNSAT does not certify the CPU or the instruction lifter.
The runnable conditional lesson provides actual comparison records and traces.

The cream, olive and russet colors follow Rewynth's existing workbench. Original
artwork and layout were prepared for this repository with Codex. Design guidance
came from Cathryn Lavery's MIT-licensed [Diagram Design](https://github.com/cathrynlavery/diagram-design/tree/38a7afb0a67a4e82308872d57de1a39590e78d71),
including its flowchart, connector, accessible-SVG and restrained-accent
principles. No template code, icons or font assets were copied. This document
records inspiration and provenance, not affiliation or endorsement.
