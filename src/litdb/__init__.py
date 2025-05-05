import litdb.lab  # noqa: F401


import os
# Set this before importing any transformers modules
# This suppresses this warning

# Using a slow image processor as `use_fast` is unset and a slow processor was
# saved with this model. `use_fast=True` will be the default behavior in v4.52,
# even if the model was saved with a slow processor. This will result in minor
# differences in outputs. You'll still be able to use a slow processor with
# `use_fast=False`.

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
