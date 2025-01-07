from dash import Dash, html
import os


def create_app():
  app = Dash(__name__)
  
  app.layout = html.Div(
    [
      html.H3('Hello World!'),
    ]
  )

  return app


if __name__ == '__main__' and 'DEBUG' in os.environ and os.environ['DEBUG'] == 'True':
  create_app().run_server(debug=True)
