import os
import shutil
import subprocess
import sys

from opendash.config import Config


def copy_directory_contents(source: str, target: str, exclude: list[str]) -> None:
  for root, dirs, files in os.walk(source):
    for directory in exclude:
      if directory in dirs:
        dirs.remove(directory)
      
    for file in files:
      source_file = os.path.join(root, file)
      target_file = os.path.join(target, os.path.relpath(source_file, source))
      os.makedirs(os.path.dirname(target_file), exist_ok=True)
      shutil.copy2(source_file, target_file)


def add_dependencies_to_requirements(requirements_path: str, dependencies: list[str]) -> None:
  with open(requirements_path, 'a') as file:
    dependency_str = '\n'.join(dependencies)
    file.write(f'\n{dependency_str}\n')


def prepare_folders(source_path: str, include_warmer: bool) -> dict[str, str]:
  script_path = os.path.dirname(os.path.realpath(__file__))

  # Create .open-dash directory alongside source directory
  source_parent = os.path.abspath(os.path.join(source_path, os.pardir))
  open_dash_path = os.path.join(source_parent, '.open-dash')

  if os.path.exists(open_dash_path):
    print(f'.open-dash directory already exists in {source_parent}. Removing...')
    shutil.rmtree(open_dash_path)

  # Create assets, warmer-function, and server-functions/default directories inside .open-dash
  os.makedirs(open_dash_path, exist_ok=True)

  assets_path = os.path.join(open_dash_path, 'assets')
  os.makedirs(assets_path, exist_ok=True)
  
  server_functions_path = os.path.join(open_dash_path, 'server-functions', 'default')
  os.makedirs(server_functions_path, exist_ok=True)
  
  warmer_function_path = None
  if include_warmer:
    warmer_function_path = os.path.join(open_dash_path, 'warmer-function')
    os.makedirs(warmer_function_path, exist_ok=True)

  return {
    'source_path': source_path,
    'script_path': script_path,
    'assets_path': assets_path,
    'open_dash_path': open_dash_path,
    'warmer_function_path': warmer_function_path,
    'server_functions_path': server_functions_path,
  }


def create(config: Config) -> None:
  print(f'Preparing dash bundle from {config.source_path}...')

  paths = prepare_folders(config.source_path, config.include_warmer)
  if not paths:
    return
  
  # Decostruct the prepare_folders_result dictionary
  if config.include_warmer:
    os.makedirs(paths['warmer_function_path'], exist_ok=True)
    copy_directory_contents(os.path.join(paths['script_path'], 'assets', 'warmer'), paths['warmer_function_path'], [])

  # Copy source directory contents into server-functions/default directory, excluding excluded_directories.
  copy_directory_contents(config.source_path, paths['server_functions_path'], config.excluded_directories)
  shutil.copy2(os.path.join(paths['script_path'], 'assets', 'assets-bundler.py'), paths['server_functions_path'])
  shutil.copy2(os.path.join(paths['script_path'], 'assets', 'server', 'index.py'), paths['server_functions_path'])
  shutil.copy2(
    os.path.join(paths['script_path'], 'assets', 'server', 'Dockerfile.lambda'),
    os.path.join(paths['server_functions_path'], 'Dockerfile'),
  )

  # aws-wsgi is used by the lambda handler to serve the Dash app.
  add_dependencies_to_requirements(
    os.path.join(paths['server_functions_path'], 'requirements.txt'),
    ['aws-wsgi>=0.2.7'],
  )

  print('Installing app dependencies...')
  pip_path = 'pip3'
  python_path = 'python3'
  if config.virtualenv_path:
    pip_path = os.path.join(config.virtualenv_path, 'bin', 'pip3')
    python_path = os.path.join(config.virtualenv_path, 'bin', 'python3')

  requirements_path = os.path.join(paths['server_functions_path'], 'requirements.txt')
  result = subprocess.run(
    [pip_path, '--disable-pip-version-check', 'install', '--no-cache', '-r', requirements_path],
    text=True,
    env=os.environ,
    capture_output=True,
  )
  print(result.stdout)
  print(result.stderr)

  print('Bundling React assets...')
  assets_bundler_path = os.path.join(paths['server_functions_path'], 'assets-bundler.py')
  os.environ['OPEN_DASH_ASSETS_PATH'] = paths['assets_path']
  os.environ['OPEN_DASH_FINGERPRINT_METHOD'] = config.fingerprint.method.value
  os.environ['OPEN_DASH_INCLUDE_INDEX_HTML'] = '1' if config.include_index_html else '0'
  os.environ['OPEN_DASH_INCLUDE_FINGERPRINT_VERSION'] = '1' if config.fingerprint.include_version else '0'
  result = subprocess.run(
    [python_path, assets_bundler_path],
    text=True,
    env=os.environ,
    capture_output=True,
    cwd=paths['server_functions_path'],
  )
  print(result.stdout)
  if result.stderr:
    print(result.stderr)
    sys.exit(1)

  if os.path.exists(os.path.join(config.source_path, 'assets')):
    # Copy contents of assets directory into .open-dash/assets directory. Note that the server functions directory
    # has a copy of the assets directory as well, if it exists, to ensure that the assets are available to the
    # fallback server function.
    copy_directory_contents(os.path.join(config.source_path, 'assets'), paths['assets_path'], [])
  
  print('Cleaning up...')
  os.remove(assets_bundler_path)
  if os.path.exists(os.path.join(paths['server_functions_path'], '__pycache__')):
    shutil.rmtree(os.path.join(paths['server_functions_path'], '__pycache__'))
  
  print(f"Bundling complete! Bundle is available in {paths['open_dash_path']}")
