#!/usr/bin/env python

from dash import _dash_renderer, Dash, dash_table, dcc, fingerprint, html
import importlib
import os
import shutil
import sys
import time

# The create_app function should return a Dash instance.
from app import create_app

app = create_app()


global_fingerprint = int(time.time())

# Note that the extra space in the path list is intentional to ensure that the path will have a trailing slash.
dash_sub_package_paths = [
  os.path.join('dash', 'dcc', ''),
  os.path.join('dash', 'html', ''),
  os.path.join('dash', 'dash_table', ''),
]
def is_dash_sub_package(dependency: str) -> bool:
  for path in dash_sub_package_paths:
    if dependency.startswith(path):
      return True
  
  return False

def add_relative_package_paths(packages: list[tuple[str, list[str]]], dependencies: dict, stage: str) -> None:
  if 'relative_package_path' not in dependencies:
    return
  
  if isinstance(dependencies['relative_package_path'], str):
    namespace = dependencies['namespace']
    relative_package_path = dependencies['relative_package_path']
    package = os.path.join(namespace, relative_package_path)
    if is_dash_sub_package(package):
      namespace = f"{namespace}.{os.path.split(relative_package_path)[0]}"
    
    packages.append((namespace, [package]))
    return
  
  if stage not in dependencies['relative_package_path']:
    return
  
  paths = []
  namespace = dependencies['namespace']
  for relative_package_path in dependencies['relative_package_path'][stage]:
    package = os.path.join(namespace, relative_package_path)
    paths.append(package)

    if is_dash_sub_package(package):
      namespace = f"{namespace}.{os.path.split(relative_package_path)[0]}"
  
  packages.append((namespace, paths))

def namespace_version_lookup(packages: list[tuple[str, list[str]]]) -> dict[str, str]:
  lookup = {}
  for namespace, _ in packages:
    if namespace in lookup:
      continue
    
    lookup[namespace] = importlib.import_module(namespace).__version__
  
  return lookup

def internal_dependencies(app: Dash) -> list[tuple[str, list[str]]]:
  dependency_groups = [
    _dash_renderer._js_dist_dependencies,
    _dash_renderer._js_dist,
    dcc._js_dist,
    dash_table._js_dist,
    html._js_dist,
    app.scripts.get_all_scripts(),
    app.css.get_all_css()
  ]

  packages: list[tuple[str, list[str]]] = []
  for group in dependency_groups:
    for dependencies in group:
      add_relative_package_paths(packages, dependencies, 'prod')

  return packages

def asset_file_name(namespace_versions: dict[str, str], namespace: str, dependency_path: str) -> str:
  timestamp = None
  if os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'global':
    timestamp = global_fingerprint
  elif os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'last-modified':
    timestamp = int(time.time())
  
  version = namespace_versions[namespace] if os.environ['OPEN_DASH_INCLUDE_FINGERPRINT_VERSION'] == '1' else None

  if timestamp and version:
    return fingerprint.build_fingerprint(
      os.path.basename(dependency_path),
      version,
      timestamp,
    )
  
  filename, extension = dependency_path.split("/")[-1].split(".", 1)
  if timestamp:
    # Note that the version is still included in the filename to ensure that the filename matches the expected format: 
    #   <filename>.v<version>.m<timestamp>.<extension>
    # Dash does not use the version or timestamp in the filename, it just validates that the filename matches the
    # expected format and returns the filename without a fingerprint.
    return f"{filename}.v0.m{timestamp}.{extension}"
  
  if version:
    # Note that the timestamp is still included in the filename to ensure that the filename matches the expected format:
    #   <filename>.v<version>.m<timestamp>.<extension>
    # Dash does not use the version or timestamp in the filename, it just validates that the filename matches the
    # expected format and returns the filename without a fingerprint.
    return f"{filename}.v{version}.m0.{extension}"
  
  return os.path.basename(dependency_path)

if __name__ == '__main__':
  assets_path = os.environ['OPEN_DASH_ASSETS_PATH']
  dependency_packages = internal_dependencies(app)
  namespace_versions = namespace_version_lookup(dependency_packages)

  for namespace, dependencies in dependency_packages:
    namespace_prefix = os.path.join(*f'{namespace}.'.split('.'))
    namespace_path = os.path.dirname(sys.modules[namespace].__file__)
    for dependency_path in dependencies:
      source = os.path.join(namespace_path, dependency_path.replace(namespace_prefix, ''))
      if not os.path.exists(source):
        print(f'Warning: Dependency {source} not found, skipping...')
        continue

      target_directory = os.path.dirname(os.path.join(assets_path, dependency_path))
      os.makedirs(target_directory, exist_ok=True)

      filename = asset_file_name(namespace_versions, namespace, dependency_path)
      shutil.copy2(source, os.path.join(target_directory, filename))
  
  if os.environ['OPEN_DASH_INCLUDE_INDEX_HTML'] == '1':
    # Capture index.html and write it to assets directory to optionally make it the CloudFront default object.
    # Note that the default fingerprint for all assets matches the index.html references.
    index_html = app.index()
    with open(os.path.join(assets_path, 'index.html'), 'w') as f:
      f.write(index_html)
  
  if os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'global':
    with open(os.path.join(assets_path, 'FINGERPRINT_ID'), 'w') as f:
      f.write(str(global_fingerprint))
