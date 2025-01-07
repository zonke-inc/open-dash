from dash import html, register_page


register_page(
  __name__,
  path='/about',
  title="About Page",
  description="The about page of the multi-page-lambda example."
)

layout = html.H1('Welcome to the about page!')
