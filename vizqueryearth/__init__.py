"""vizqueryearth: check and edit queryearth rules on a globe, in the browser.

The web page (web/) runs this package in the browser with queryearth: Session
holds the rules a page shows and answers its calls, and the shapes module turns
what is drawn on the globe into queryearth spaces and back.
"""

from vizqueryearth.session import Session, infer, upgrade

__all__ = ["Session", "infer", "upgrade"]
