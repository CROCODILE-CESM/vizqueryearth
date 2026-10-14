"""vizqueryearth: check and edit queryearth rules on a globe, in the browser.

The web page (web/) runs this package in the browser with queryearth. The same
package works in Python: RuleFile edits a rule file, checked by queryearth at
every step, and the shapes module turns drawn GeoJSON into rule shapes.
"""

from vizqueryearth.rulefile import RuleFile, guess_dimensions
from vizqueryearth.shapes import Shape, antarctic, arctic, from_drawn

__all__ = [
    "RuleFile",
    "Shape",
    "antarctic",
    "arctic",
    "from_drawn",
    "guess_dimensions",
]
