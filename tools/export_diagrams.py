"""Export the two explicit, self-contained SVGs from the editable XHTML source.

No layout engine, external stylesheet or network request is involved.
Run from any directory: python tools/export_diagrams.py
"""

from pathlib import Path
import xml.etree.ElementTree as ET


def main():
    folder = Path(__file__).resolve().parents[1] / "docs" / "diagrams"
    namespace = "http://www.w3.org/2000/svg"
    root = ET.parse(folder / "comparison.html").getroot()
    diagrams = list(root.iter(f"{{{namespace}}}svg"))
    expected = {"comparison", "comparison-mobile"}
    if {node.get("id") for node in diagrams} != expected or len(diagrams) != 2:
        raise ValueError("Expected exactly the two named comparison diagrams")
    ET.register_namespace("", namespace)
    for node in diagrams:
        # All styles and marker IDs are local to each SVG. The source contains
        # no nested SVGs or HTML-only attributes requiring an import transform.
        target = folder / (node.get("id") + ".svg")
        target.write_text(ET.tostring(node, encoding="unicode").strip() + "\n",
                          encoding="utf-8")
        print(target.relative_to(folder.parents[1]))


if __name__ == "__main__":
    main()
