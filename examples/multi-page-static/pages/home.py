from dash import html, register_page


register_page(
  __name__,
  path='/',
  title="Homepage",
  description="The home page of the multi-page-static example."
)

layout = html.H1('Welcome to the home page!')
