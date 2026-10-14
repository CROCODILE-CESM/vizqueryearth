"""vizqueryearth: draw the shapes of queryearth rules on a map in Jupyter.

draw() shows a map to draw one shape on; Editor draws and edits the shapes of
the rules in a rule file. queryearth checks every shape and every rule.
"""

from vizqueryearth.shapes import Shape, antarctic, arctic, from_leaflet, to_leaflet
from vizqueryearth.widgets import Drawing, Editor, draw

__all__ = [
    "Drawing",
    "Editor",
    "Shape",
    "antarctic",
    "arctic",
    "draw",
    "from_leaflet",
    "to_leaflet",
]
