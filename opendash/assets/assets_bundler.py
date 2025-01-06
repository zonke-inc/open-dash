#!/usr/bin/env python

from dash import _dash_renderer, Dash, dash_table, dcc, fingerprint, html, page_registry
from dataclasses import dataclass
from enum import Enum
from flask.testing import FlaskClient
import importlib
import os
import shutil
import sys
import time

from open_dash_output import CloudFrontBehavior, CloudFrontConfig, FunctionOrigin, MiscBundle, OpenDashOutput, S3Origin, S3OriginCopy

# The create_app function should return a Dash instance.
from app import create_app


app = create_app()
global_fingerprint = int(time.time())


@dataclass(kw_only=True)
class PackagePaths:
  namespace: str
  is_async: bool
  is_dynamic: bool
  relative_paths: list[str]


class RequestMethod(Enum):
  GET = "get"
  POST = "global"


update_components_params = {
  'output': '.._pages_content.children..._pages_store.data..',
  'outputs': [
    { 'id': '_pages_content', 'property': 'children' },
    { 'id': '_pages_store', 'property': 'data' }
  ],
  'inputs': [
    { 'id': '_pages_location', 'property': 'pathname', 'value': '/' },
    { 'id': '_pages_location', 'property': 'search', 'value': '' }
  ],
  'changedPropIds': ['_pages_location.pathname'],
  'parsedChangedPropsIds': ['_pages_location.pathname']
}


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

def add_relative_package_paths(packages: list[PackagePaths], dependencies: dict, stage: str) -> None:
  if 'relative_package_path' not in dependencies:
    return
  
  if isinstance(dependencies['relative_package_path'], str):
    namespace = dependencies['namespace']
    is_dynamic = dependencies.get('dynamic', False)
    relative_package_path = dependencies['relative_package_path']
    is_async = dependencies.get('async', False) in [True, 'eager']
    package = os.path.join(namespace, relative_package_path)
    if is_dash_sub_package(package):
      namespace = f"{namespace}.{os.path.split(relative_package_path)[0]}"
    
    packages.append(PackagePaths(
      is_async=is_async,
      namespace=namespace,
      is_dynamic=is_dynamic,
      relative_paths=[package]
    ))
    return
  
  if stage not in dependencies['relative_package_path']:
    return
  
  paths = []
  namespace = dependencies['namespace']
  is_dynamic = dependencies.get('dynamic', False)
  is_async = dependencies.get('async', False) in [True, 'eager']
  for relative_package_path in dependencies['relative_package_path'][stage]:
    package = os.path.join(namespace, relative_package_path)
    paths.append(package)

    if is_dash_sub_package(package):
      namespace = f"{namespace}.{os.path.split(relative_package_path)[0]}"
  
  packages.append(PackagePaths(
    is_async=is_async,
    namespace=namespace,
    is_dynamic=is_dynamic,
    relative_paths=paths
  ))

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

def namespace_version_lookup(packages: list[PackagePaths]) -> dict[str, str]:
  lookup = {}
  for pkg in packages:
    if pkg.namespace in lookup:
      continue
    
    lookup[pkg.namespace] = importlib.import_module(pkg.namespace).__version__
  
  return lookup

def internal_dependencies(app: Dash) -> list[PackagePaths]:
  dependency_groups = [
    _dash_renderer._js_dist_dependencies,
    _dash_renderer._js_dist,
    dcc._js_dist,
    dash_table._js_dist,
    html._js_dist,
    app.scripts.get_all_scripts(),
    app.css.get_all_css()
  ]

  packages: list[PackagePaths] = []
  for group in dependency_groups:
    for dependencies in group:
      add_relative_package_paths(packages, dependencies, 'prod')

  return packages

"""
Dash apps call the /_dash-layout and /_dash-dependencies routes from the client side to retrieve the layout and 
additional dependencies. Since these values do not change after the app is built, we can write them to the static 
directory to avoid unnecessary calls to the Dash server.
"""
def write_layout_and_dependencies(app: Dash, static_path: str) -> None:
  with app.server.test_request_context():
    with app.server.test_client() as client:
      layout = client.get('/_dash-layout')
      if layout.status_code == 200:
        with open(os.path.join(static_path, '_dash-layout'), 'w') as f:
          f.write(layout.data.decode('UTF-8'))
      
      dependencies = client.get('/_dash-dependencies')
      if dependencies.status_code == 200:
        with open(os.path.join(static_path, '_dash-dependencies'), 'w') as f:
          f.write(dependencies.data.decode('UTF-8'))


def cache_request(client: FlaskClient, url: str, target_path: str, method: RequestMethod, params: dict) -> int:
  response = client.get(url) if method == RequestMethod.GET else client.post(url, json=params)
  if response.status_code == 200:
    with open(target_path, 'w') as f:
      f.write(response.data.decode('UTF-8'))
  
  return response.status_code

"""
Exports index.html and other static pages to the static directory.

Dash apps call the /_dash-layout and /_dash-dependencies routes from the client side to retrieve the layout and 
additional dependencies. Since these values do not change after the app is built, we can write them to the static 
directory to avoid unnecessary calls to the Dash server.

If this is a multi-page application, we also export the /_dash-update-component route for each page to the static
directory. This is only done for pages assumed to be static, i.e. pages that do not have path variables. If your site
uses cookies to display different content for the same path, you will need to ignore contents of the static directory.
"""
def export_static_pages(app: Dash, static_path: str) -> S3Origin:
  s3Copy: list[S3OriginCopy] = []
  url_base = app.config.get('url_base_pathname')
  copy_source_prefix = os.path.join('.open-dash', 'static')
  if url_base is None:
    url_base = '/'
  else:
    url_base_components = url_base.split('/')[1:]
    static_path = os.path.join(static_path, *url_base_components)
    copy_source_prefix = os.path.join(copy_source_prefix, *url_base_components)
    os.makedirs(static_path, exist_ok=True)
  
  copy_target_prefix = url_base.replace('/', '', 1) if url_base.startswith('/') else None
  
  mimetypes: dict[str, str] = {}
  # Capture index.html and write it to static directory to optionally make it the CloudFront default object.
  # Note that the default fingerprint for all static matches the index.html references.
  with app.server.test_request_context():
    with app.server.test_client() as client:
      with open(os.path.join(static_path, 'index.html'), 'w') as f:
        index_html = client.get(url_base).data.decode('UTF-8')
        f.write(index_html.replace('http://localhost', f'https://{os.environ["OPEN_DASH_DOMAIN_NAME"]}'))
        s3Copy.append(S3OriginCopy(
          source=os.path.join(copy_source_prefix, 'index.html'),
          target=os.path.join(copy_target_prefix, 'index.html') if copy_target_prefix else 'index.html',
        ))
      
      status_code = cache_request(
        client,
        f'{url_base}_dash-layout',
        os.path.join(static_path, '_dash-layout'),
        RequestMethod.GET,
        {}
      )
      if status_code == 200:
        target_path = os.path.join(copy_target_prefix, '_dash-layout') if copy_target_prefix else '_dash-layout'
        s3Copy.append(S3OriginCopy(
          source=os.path.join(copy_source_prefix, '_dash-layout'),
          target=target_path,
        ))
        mimetypes[target_path] = 'application/json'
      
      status_code = cache_request(
        client,
        f'{url_base}_dash-dependencies',
        os.path.join(static_path, '_dash-dependencies'),
        RequestMethod.GET,
        {}
      )
      if status_code == 200:
        target_path = os.path.join(copy_target_prefix, '_dash-dependencies') if copy_target_prefix else '_dash-dependencies'
        s3Copy.append(S3OriginCopy(
          source=os.path.join(copy_source_prefix, '_dash-dependencies'),
          target=target_path,
        ))
        mimetypes[target_path] = 'application/json'
  
      if page_registry:
        has_custom_404 = False
        target_directory = os.path.join(static_path, '_dash-update-component')
        copy_source_prefix = os.path.join(copy_source_prefix, '_dash-update-component')
        copy_target_prefix = os.path.join(copy_target_prefix, '_dash-update-component')
        os.makedirs(target_directory, exist_ok=True)
        for page in page_registry.values():
          if page.get('relative_path').endswith('/404'):
            has_custom_404 = True
          
          if page.get('path_template'):
            print(f"Skipping page '{page.get('name')}' with path variables", page.get('path_template'))
            continue

          page_path = page.get('path')
          if page.get('path') != '/' and page.get('path').startswith('/'):
            page_path = page.get('path').replace('/', '', 1)
          elif page_path == '/':
              # NOTE: This index page is different from the index.html page in a multi-page application. In a multi-page
              #       application, most (if not all) pages will be fetched as JSON content using the 
              #       _dash-update-component route and rendered by the client.
              page_path = 'index'

          params = update_components_params.copy()
          # Note that the value of the pathname input is the relative path of the page which includes the base url.
          params['inputs'][0]['value'] = page.get('relative_path')
          status_code = cache_request(
            client,
            f'{url_base}_dash-update-component',
            os.path.join(target_directory, page_path),
            RequestMethod.POST,
            params,
          )
          if status_code == 200:
            s3Copy.append(S3OriginCopy(
              source=os.path.join(copy_source_prefix, page_path),
              target=os.path.join(copy_target_prefix, page_path),
            ))
            mimetypes[os.path.join(copy_target_prefix, page_path)] = 'application/json'
        
        if not has_custom_404:
          status_code = cache_request(
            client,
            f'{url_base}_dash-update-component',
            os.path.join(target_directory, '404'),
            RequestMethod.POST,
            update_components_params,
          )
          if status_code == 200:
            s3Copy.append(S3OriginCopy(
              source=os.path.join(copy_source_prefix, '404'),
              target=os.path.join(copy_target_prefix, '404'),
            ))
            mimetypes[os.path.join(copy_target_prefix, '404')] = 'application/json'
  
  return S3Origin(
    copy=s3Copy,
    mimetypes=mimetypes,
    origin_path_prefix=url_base[0:len(url_base) - 1] if url_base.endswith('/') else url_base,
  )

def asset_file_name(namespace_versions: dict[str, str], namespace: str, dependency_path: str, source_path: str) -> str:
  timestamp = None
  if os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'global':
    timestamp = global_fingerprint
  elif os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'last-modified':
    timestamp = int(os.stat(source_path).st_mtime)
  
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
  static_path = os.environ['OPEN_DASH_STATIC_PATH']

  behaviors = []
  origin_path_prefix = None
  default_root_object = None
  origins: dict[str, S3Origin | FunctionOrigin] = {}
  if os.environ['OPEN_DASH_EXPORT_STATIC'] == '1':
    origins['s3'] = export_static_pages(app, static_path)

    if origins['s3'].origin_path_prefix.startswith('/'):
      origin_path_prefix = origins['s3'].origin_path_prefix.replace('/', '', 1)
     
    if origins['s3'].find_copy(target_prefix='_dash-update-component/'):
      behaviors.append(CloudFrontBehavior(
        origin='s3',
        pattern=os.path.join(origin_path_prefix, '_dash-update-component') if origin_path_prefix else '_dash-update-component',
      ))
    
    behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=os.path.join(origin_path_prefix, '_dash-layout') if origin_path_prefix else '_dash-layout',
    ))
    behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=os.path.join(origin_path_prefix, '_dash-dependencies') if origin_path_prefix else '_dash-dependencies',
    ))

    index_item = origins['s3'].find_copy(target_suffix='index.html')
    default_root_object = index_item.target if index_item else None

  components_path = os.path.join(static_path, '_dash-component-suites')
  if origin_path_prefix:
    components_path = os.path.join(static_path, origin_path_prefix, '_dash-component-suites')
  
  dependency_packages = internal_dependencies(app)
  namespace_versions = namespace_version_lookup(dependency_packages)
  for pkg in dependency_packages:
    namespace_prefix = os.path.join(*f'{pkg.namespace}.'.split('.'))
    namespace_path = os.path.dirname(sys.modules[pkg.namespace].__file__)
    for dependency_path in pkg.relative_paths:
      source = os.path.join(namespace_path, dependency_path.replace(namespace_prefix, ''))
      if not os.path.exists(source):
        print(f'Warning: Dependency {source} not found, skipping...')
        continue

      target_directory = os.path.dirname(os.path.join(components_path, dependency_path))
      os.makedirs(target_directory, exist_ok=True)

      filename = asset_file_name(namespace_versions, pkg.namespace, dependency_path, source)
      shutil.copy2(source, os.path.join(target_directory, filename))

      if pkg.is_dynamic or pkg.is_async:
        # Copy the original filename if the dependency is dynamic or async because the client can potentially request 
        # the unfingerprinted file.
        # 
        # NOTE: This creates a duplicate file in the assets directory so we should investigate if there is a way to
        #      determine ahead of time if the client will request the fingerprinted or unfingerprinted file.
        shutil.copy2(source, os.path.join(target_directory, os.path.basename(dependency_path)))
  
  if 's3' not in origins:
    origins['s3'] = S3Origin(
      copy=[],
      mimetypes={},
      origin_path_prefix='',
    )
  
  origins['s3'].copy.append(S3OriginCopy(
    source=os.path.join('.open-dash', 'static', '_dash-component-suites'),
    target=os.path.join(origin_path_prefix, '_dash-component-suites') if origin_path_prefix else '_dash-component-suites',
  ))
  behaviors.append(CloudFrontBehavior(
    origin='s3',
    pattern=os.path.join(origin_path_prefix, '_dash-component-suites/*') if origin_path_prefix else '_dash-component-suites/*',
  ))
  
  origins['default'] = FunctionOrigin(
    handler='index.handler',
    dockerfile='Dockerfile',
    bundle=os.path.join('.open-dash', os.environ['OPEN_DASH_SERVER_FUNCTIONS_PATH'].split('.open-dash/')[-1]),
  )
  behaviors.append(CloudFrontBehavior(
    origin='default',
    pattern='*',
  ))
  
  additional_bundles = {}
  if 'OPEN_DASH_WARMER_FUNCTION_PATH' in os.environ:
    additional_bundles['warmer'] = MiscBundle(
      handler='index.handler',
      bundle=os.path.join('.open-dash', os.environ['OPEN_DASH_WARMER_FUNCTION_PATH'].split('.open-dash/')[-1]),
    )

  if 'OPEN_DASH_ASSETS_PATH' in os.environ:
    # Copy the assets directory into the .open-dash/static directory. Note that the server functions directory
    # has a copy of the assets directory as well, if it exists, to ensure that the assets are available to the
    # fallback server function.
    copy_directory_contents(
      os.environ['OPEN_DASH_ASSETS_PATH'],
      os.path.join(static_path, origin_path_prefix, 'assets') if origin_path_prefix else os.path.join(static_path, 'assets'),
      []
    )

    behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=os.path.join(origin_path_prefix, 'assets/*') if origin_path_prefix else 'assets/*',
    ))
    origins['s3'].copy.append(S3OriginCopy(
      source=os.path.join('.open-dash', 'static', 'assets'),
      target=os.path.join(origin_path_prefix, 'assets') if origin_path_prefix else 'assets',
    ))
  
  if 'OPEN_DASH_DATA_PATH' in os.environ:
    copy_directory_contents(
      os.environ['OPEN_DASH_DATA_PATH'],
      os.path.join(origin_path_prefix, 'data') if origin_path_prefix else 'data',
      []
    )

    additional_bundles['data_path'] = MiscBundle(
      bundle=os.path.join('.open-dash', 'data'),
    )
  
  output = OpenDashOutput(
    additional_bundles=additional_bundles,
    global_fingerprint=global_fingerprint if os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'global' else None,
    cloud_front_config=CloudFrontConfig(
      origins=origins,
      behaviors=behaviors,
      default_root_object=default_root_object,
    ),
  )

  with open(os.path.join(static_path, '..', 'open-dash.output.json'), 'w') as f:
    f.write(output.to_json())
