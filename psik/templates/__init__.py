# Valid backends must contain mustache formatted template files
# for the following:

actions = ['submit', 'cancel', 'job']

from .renderer import check, list_backends, render, render_all
