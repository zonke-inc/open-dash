import glob
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


def prepare_folders(config: Config) -> dict[str, str]:
  script_path = os.path.dirname(os.path.realpath(__file__))

  open_dash_path = os.path.join(config.target_base_path, '.open-dash')

  if os.path.exists(open_dash_path):
    print(f'.open-dash directory already exists in {config.target_base_path}. Removing...')
    shutil.rmtree(open_dash_path)

  # Create static, warmer-function, and server-functions/default directories inside .open-dash
  os.makedirs(open_dash_path, exist_ok=True)

  static_path = os.path.join(open_dash_path, 'static')
  os.makedirs(static_path, exist_ok=True)
  
  server_functions_path = os.path.join(open_dash_path, 'server-functions', 'default')
  os.makedirs(server_functions_path, exist_ok=True)
  
  warmer_function_path = None
  if config.include_warmer:
    warmer_function_path = os.path.join(open_dash_path, 'warmer-function')
    os.makedirs(warmer_function_path, exist_ok=True)
  
  source_data_path = None
  if config.data_path and os.path.exists(os.path.join(config.source_path, '..', config.data_path)):
    source_data_path = os.path.join(config.source_path, '..', config.data_path)
    os.makedirs(os.path.join(open_dash_path, 'data'), exist_ok=True)

  return {
    'script_path': script_path,
    'static_path': static_path,
    'open_dash_path': open_dash_path,
    'source_path': config.source_path,
    'data_path': source_data_path or '',
    'warmer_function_path': warmer_function_path,
    'server_functions_path': server_functions_path,
  }


def install_dependencies(config: Config, paths: dict[str, str]) -> None:
  # aws-wsgi is used by the lambda handler to serve the Dash app.
  add_dependencies_to_requirements(
    os.path.join(paths['server_functions_path'], 'requirements.txt'),
    ['aws-wsgi>=0.2.7'],
  )

  pip_path = 'pip3'
  if config.virtualenv_path:
    pip_path = os.path.join(config.virtualenv_path, 'bin', 'pip3')

  requirements_path = os.path.join(paths['server_functions_path'], 'requirements.txt')
  result = subprocess.run(
    [pip_path, '--disable-pip-version-check', 'install', '--no-cache', '-r', requirements_path],
    text=True,
    env=os.environ,
    capture_output=True,
  )
  print(result.stdout)
  if result.returncode != 0:
    print(result.stderr)
    sys.exit(1)


def bundle_react_assets(config: Config, paths: dict[str, str]) -> None:
  os.environ['OPEN_DASH_DOMAIN_NAME'] = config.domain_name
  os.environ['OPEN_DASH_STATIC_PATH'] = paths['static_path']
  os.environ['OPEN_DASH_FINGERPRINT_METHOD'] = config.fingerprint.method.value
  os.environ['OPEN_DASH_EXPORT_STATIC'] = '1' if config.export_static else '0'
  os.environ['OPEN_DASH_SERVER_FUNCTIONS_PATH'] = paths['server_functions_path']
  os.environ['OPEN_DASH_INCLUDE_FINGERPRINT_VERSION'] = '1' if config.fingerprint.include_version else '0'
  if config.include_warmer:
    os.environ['OPEN_DASH_WARMER_FUNCTION_PATH'] = paths['warmer_function_path']
  
  if config.data_path:
    os.environ['OPEN_DASH_SOURCE_DATA_PATH'] = paths['data_path']
  
  if os.path.exists(os.path.join(config.source_path, 'assets')):
    os.environ['OPEN_DASH_ASSETS_PATH'] = os.path.join(config.source_path, 'assets')

  python_path = 'python3'
  if config.virtualenv_path:
    python_path = os.path.join(config.virtualenv_path, 'bin', 'python3')
  
  assets_bundler_path = os.path.join(paths['server_functions_path'], 'assets_bundler.py')
  result = subprocess.run(
    [python_path, assets_bundler_path],
    text=True,
    env=os.environ,
    capture_output=True,
    cwd=paths['server_functions_path'],
  )
  print(result.stdout)
  if result.returncode != 0:
    print(result.stderr)
    sys.exit(1)


def clean_env_vars() -> None:
  env_vars = []
  for key in os.environ:
    if key.startswith('OPEN_DASH_'):
      env_vars.append(key)
  
  for key in env_vars:
    del os.environ[key]

def create(config: Config) -> None:
  print(f'Preparing dash bundle from {config.source_path}...')

  paths = prepare_folders(config)
  
  # Decostruct the prepare_folders_result dictionary
  if config.include_warmer:
    os.makedirs(paths['warmer_function_path'], exist_ok=True)
    copy_directory_contents(os.path.join(paths['script_path'], 'assets', 'warmer'), paths['warmer_function_path'], [])

  # Copy source directory contents into server-functions/default directory, excluding excluded_directories.
  copy_directory_contents(config.source_path, paths['server_functions_path'], config.excluded_directories)
  shutil.copy2(os.path.join(paths['script_path'], 'assets', 'assets_bundler.py'), paths['server_functions_path'])
  shutil.copy2(os.path.join(paths['script_path'], 'assets', 'server', 'index.py'), paths['server_functions_path'])
  shutil.copy2(os.path.join(paths['script_path'], 'assets', 'open_dash_output.py'), paths['server_functions_path'])
  shutil.copy2(
    os.path.join(paths['script_path'], 'assets', 'server', 'Dockerfile.lambda'),
    os.path.join(paths['server_functions_path'], 'Dockerfile'),
  )

  try:
    print('Installing app dependencies...')
    install_dependencies(config, paths)

    print('Bundling React assets...')
    bundle_react_assets(config, paths)
  finally:
    clean_env_vars()
  
  print('Cleaning up...')
  os.remove(os.path.join(paths['server_functions_path'], 'assets_bundler.py'))
  os.remove(os.path.join(paths['server_functions_path'], 'open_dash_output.py'))
  for file in glob.glob(os.path.join(paths['open_dash_path'], '**', '*.pyc'), recursive=True):
    os.remove(file)
  
  for file in glob.glob(os.path.join(paths['open_dash_path'], '**', 'cache.db'), recursive=True):
    os.remove(file)
  
  print(f"Bundling complete! Bundle is available in {paths['open_dash_path']}")
