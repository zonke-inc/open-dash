#!/usr/bin/env python

from dash import _dash_renderer, Dash, dash_table, dcc, fingerprint, html
import importlib
import os
import shutil
import subprocess
import sys

# The create_app function should return a Dash instance.
from app import create_app

app = create_app()


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

def js_dist_dependencies(app: Dash) -> list[tuple[str, list[str]]]:
  packages: list[tuple[str, list[str]]] = []
  for dependencies in _dash_renderer._js_dist_dependencies:
    add_relative_package_paths(packages, dependencies, 'prod')
  
  for dependencies in _dash_renderer._js_dist:
    add_relative_package_paths(packages, dependencies, 'prod')
  
  for dependencies in dcc._js_dist:
    add_relative_package_paths(packages, dependencies, 'prod')
  
  for dependencies in dash_table._js_dist:
    add_relative_package_paths(packages, dependencies, 'prod')
  
  for dependencies in html._js_dist:
    add_relative_package_paths(packages, dependencies, 'prod')
  
  for dependencies in app.scripts.get_all_scripts():
    add_relative_package_paths(packages, dependencies, 'prod')

  return packages

if __name__ == '__main__':
  dependency_packages = js_dist_dependencies(app)

  namespace_versions = namespace_version_lookup(dependency_packages)

  assets_path = os.environ['OPEN_DASH_ASSETS_PATH']
  for namespace, dependencies in dependency_packages:
    namespace_prefix = os.path.join(*f'{namespace}.'.split('.'))
    namespace_path = os.path.dirname(sys.modules[namespace].__file__)
    for dependency_path in dependencies:
      source = os.path.join(namespace_path, dependency_path.replace(namespace_prefix, ''))
      if not os.path.exists(source):
        print(f'Warning: Dependency {source} not found, skipping...')
        continue

      target_path = os.path.dirname(os.path.join(assets_path, dependency_path))
      os.makedirs(target_path, exist_ok=True)
      
      fingerprinted = fingerprint.build_fingerprint(
        os.path.basename(dependency_path),
        namespace_versions[namespace],
        int(os.stat(source).st_mtime)
      )
      shutil.copy2(source, os.path.join(target_path, fingerprinted))
  
  # Capture index.html and write it to assets directory to optionally make it the CloudFront default object.
  # The fingerprinted assets should match the index.html references.
  index_html = app.index()
  with open(os.path.join(assets_path, 'index.html'), 'w') as f:
    f.write(index_html)
