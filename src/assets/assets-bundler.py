#!/usr/bin/env python

from dash import _dash_renderer, Dash, dash_table, dcc, html
import os
from shutil import copy2
import subprocess
import tempfile

from app import create_app

app = create_app()

def relative_package_paths(dependencies: dict, stage: str) -> list[str]:
  if 'relative_package_path' not in dependencies:
    return []
  
  if isinstance(dependencies['relative_package_path'], str):
    return [f"{dependencies['namespace']}/{dependencies['relative_package_path']}"]
  
  if stage not in dependencies['relative_package_path']:
    return []
  
  paths = []
  for dependency in dependencies['relative_package_path'][stage]:
    paths.append(f"{dependencies['namespace']}/{dependency}")
  
  return paths

def js_dist_dependencies(app: Dash) -> str:
  packages = []
  for dependencies in _dash_renderer._js_dist_dependencies:
    packages.extend(relative_package_paths(dependencies, 'prod'))
  
  for dependencies in _dash_renderer._js_dist:
    packages.extend(relative_package_paths(dependencies, 'prod'))
  
  for dependencies in dcc._js_dist:
    packages.extend(relative_package_paths(dependencies, 'prod'))
  
  for dependencies in dash_table._js_dist:
    packages.extend(relative_package_paths(dependencies, 'prod'))
  
  for dependencies in html._js_dist:
    packages.extend(relative_package_paths(dependencies, 'prod'))
  
  for dependencies in app.scripts.get_all_scripts():
    packages.extend(relative_package_paths(dependencies, 'prod'))

  return packages

if __name__ == '__main__':
  tmp_site_packages = os.path.join(tempfile.gettempdir(), 'dash-bundling', 'site-packages')
  try:
    dependency_paths = js_dist_dependencies(app)

    os.makedirs(tmp_site_packages, exist_ok=True)
    wheels_path = os.environ['OPEN_DASH_WHEELS_PATH']

    subprocess.run(
      ['pip', 'install', '--no-cache', f'{wheels_path}/*', '-t', '.'],
      cwd=tmp_site_packages,
      stdout=subprocess.PIPE,
      stderr=subprocess.STDOUT,
    )

    assets_path = os.environ['OPEN_DASH_ASSETS_PATH']
    for dependency_path in dependency_paths:
      source = os.path.join(tmp_site_packages, dependency_path)
      if not os.path.exists(source):
        continue

      target = os.path.dirname(os.path.join(assets_path, dependency_path))
      os.makedirs(target, exist_ok=True)
      copy2(source, target)
    
    # Capture index.html and write it to assets directory to optionally make it the CloudFront default object.
    index_html = app.index()
    with open(os.path.join(assets_path, 'index.html'), 'w') as f:
      f.write(index_html)
    
  finally:
    if os.path.exists(tmp_site_packages):
      os.rmdir(tmp_site_packages)
