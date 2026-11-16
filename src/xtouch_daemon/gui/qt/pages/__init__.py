"""
The pages of the editor: the selected strip (`strip`), the layout being edited (`layout`), and the global settings:
a section of options (`[behavior]`, `[mqtt]`, `[device]`, ..., in `sections`) and the aliases (`aliases`).

Every page is built once. From then on it shows the document in place: `show_document()` with the `Change` the
`Editor` reports loads the values into the fields it has, and switches between parts it built before (e.g. the form of
another strip type), instead of building itself again (see the GUI section of docs/architecture.md).
"""
