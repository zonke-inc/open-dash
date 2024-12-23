import os
from shutil import copy2
import subprocess


def copy_directory_contents(source: str, target: str, exclude: list[str]) -> None:
  for root, dirs, files in os.walk(source):
    for directory in exclude:
      if directory in dirs:
        dirs.remove(directory)
      
    for file in files:
      source_file = os.path.join(root, file)
      target_file = os.path.join(target, os.path.relpath(source_file, source))
      os.makedirs(os.path.dirname(target_file), exist_ok=True)
      copy2(source_file, target_file)


def add_dependencies_to_requirements(requirements_path: str, dependencies: list[str]) -> None:
  with open(requirements_path, 'a') as file:
    dependency_str = '\n'.join(dependencies)
    file.write(f'\n{dependency_str}\n')


def create(source_path: str, excluded_directories: list[str], include_warmer: bool) -> None:
  print(f'Bundling assets from {source_path}...')

  # Create .open-dash directory alongside source directory
  source_parent = os.path.abspath(os.path.join(os.pardir, source_path))

  # Create assets, warmer-function, and server-functions/default directories inside .open-dash
  open_dash_path = os.path.join(source_parent, '.open-dash')
  os.makedirs(open_dash_path, exist_ok=True)

  assets_path = os.path.join(open_dash_path, 'assets')
  os.makedirs(assets_path, exist_ok=True)
  
  server_functions_path = os.path.join(open_dash_path, 'server-functions', 'default')
  os.makedirs(server_functions_path, exist_ok=True)
  
  warmer_function_path = os.path.join(open_dash_path, 'warmer-function')
  if include_warmer:
    os.makedirs(warmer_function_path, exist_ok=True)
    copy_directory_contents(os.path.join('assets', 'warmer'), warmer_function_path, [])

  # Copy source directory contents into server-functions/default directory, excluding excluded_directories.
  copy_directory_contents(source_path, server_functions_path, excluded_directories)
  copy2(os.path.join('assets', 'index.py'), server_functions_path)
  copy2(os.path.join('assets', 'assets-bundler.py'), server_functions_path)
  copy2(os.path.join('assets', 'Dockerfile.lambda'), server_functions_path)

  # aws-wsgi is used by the lambda handler to serve the Dash app.
  add_dependencies_to_requirements(
    os.path.join(server_functions_path, 'requirements.txt'),
    ['aws-wsgi>=0.2.7'],
  )
  wheels_path = os.path.join(server_functions_path, 'wheels')
  os.makedirs(wheels_path, exist_ok=True)

  os.environ['PYTHONUNBUFFERED'] = '1'
  os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
  subprocess.run(
    ['pip', 'wheel', '--wheel-dir', 'wheels', '-r', 'requirements.txt'],
    env=os.environ,
    cwd=server_functions_path,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
  )

  os.environ['OPEN_DASH_ASSETS_PATH'] = assets_path
  os.environ['OPEN_DASH_WHEELS_PATH'] = wheels_path
  subprocess.run(
    ['python3', os.path.join(server_functions_path, 'assets-bundler.py')],
    env=os.environ,
    cwd=server_functions_path,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
  )

  if os.path.exists(os.path.join(source_path, 'assets')):
    # Copy contents of assets directory into .open-dash/assets directory. Note that the server functions dierctory
    # has a copy of the assets directory as well, if it exists, to ensure that the assets are available to the
    # fallback server function.
    copy_directory_contents(os.path.join(source_path, 'assets'), assets_path, [])
  