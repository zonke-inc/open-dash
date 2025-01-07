from dash import Dash, page_container
from dash_bootstrap_components import Container
import os


def create_app():
  app = Dash(__name__, use_pages=True)
  
  app.layout = Container(
    [page_container],
    fluid=True,
  )

  return app


if __name__ == '__main__' and 'DEBUG' in os.environ and os.environ['DEBUG'] == 'True':
  create_app().run_server(debug=True)
