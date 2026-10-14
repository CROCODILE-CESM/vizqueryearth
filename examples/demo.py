# %% [markdown]
# # vizqueryearth demo
#
# Run the cells one at a time in VS Code or JupyterLab. Everything here is made
# up: the products, the rules and the model.

# %%
import shutil
from pathlib import Path

import queryearth as qe

import vizqueryearth as vq

# %% [markdown]
# ## Draw one shape
#
# Draw a polygon or a rectangle with the tools on the left of the map. A
# rectangle becomes a box. Draw across the date line if you like: queryearth
# splits the shape at ±180.

# %%
d = vq.draw()
d

# %%
print(d.shape)  # run after drawing
rule = qe.Rule(
    code="MINE001",
    kind="warning",
    title="Example",
    message="A rule whose shape was drawn on the map.",
    scope=qe.Scope(space=d.space),
)
print(rule.to_feature()["geometry"])

# %% [markdown]
# ## Edit the shapes of a rule file
#
# The editor works on a copy of the demo rules. Pick a rule in the list or
# click its shape, then draw, drag or delete shapes on the map, or type a box.
# **Apply** keeps the change, **Save file** checks every rule with queryearth and
# writes the file. The Arctic rule reaches past the map's edge, so it is shown cut
# off at 85° and edited with the box fields.

# %%
path = Path("my_rules.geojson")  # run from examples/, next to demo_rules.geojson
shutil.copy("demo_rules.geojson", path)
ed = vq.Editor(path, vocabulary={"product": ["demo_atmos"]})
ed

# %% [markdown]
# The same steps from code:

# %%
ed.add("DEMO005", title="Example", message="Added from code.")
ed.set_shape(vq.arctic(75))
ed.apply()
ed.save()
print(qe.Registry("check").load(path))
