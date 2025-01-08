#!/usr/bin/env python

"""
This script bundles Dash assets for deployment on AWS. It is copied into the user's application directory and run as a
script to create the OpenDash output. It statically extracts JavaScript dependencies from the Dash app and spins up a
Flask test client to make requests to the Dash server for the layout and dependencies of each page.
"""
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


class BundlerUtils:
  @staticmethod
  def join_path(prefix: str, suffix: str) -> str:
    return os.path.join(prefix, suffix) if prefix else suffix


  @staticmethod
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


  @staticmethod
  def asset_file_name(version: str | None, dependency_path: str, source_path: str) -> str:
    timestamp = None
    if os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'global':
      timestamp = global_fingerprint
    elif os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'last-modified':
      timestamp = int(os.stat(source_path).st_mtime)

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


class DependencyLookup:
  # Note that the extra space in the path list is intentional to ensure that the path will have a trailing slash.
  dash_sub_package_paths = [
    os.path.join('dash', 'dcc', ''),
    os.path.join('dash', 'html', ''),
    os.path.join('dash', 'dash_table', ''),
  ]


  def __init__(self, app: Dash):
    self.__app = app
    self.__lookup: dict[str, str] = {}
    self.__packages: list[PackagePaths] = []
  

  def namespace_version(self, namespace: str) -> str:
    if not self.__lookup:
      for pkg in self.get_internal_dependencies():
        if pkg.namespace in self.__lookup:
          continue
        
        self.__lookup[pkg.namespace] = importlib.import_module(pkg.namespace).__version__
    
    if os.environ['OPEN_DASH_INCLUDE_FINGERPRINT_VERSION'] == '1':
      return self.__lookup[namespace]
    
    return None


  def get_internal_dependencies(self) -> list[PackagePaths]:
    """
    In the best case scenario, this particular function would live in the Dash repository and publicly accessible to 3P
    developers. Right now, it is vulnerable to breaking changes in the Dash codebase because there is no explicit 
    contract between the Dash codebase and the OpenDash codebase.

    TODO: Work with the Dash maintainers to create a public API for accessing the internal dependencies of a Dash app.
    """
    if not self.__packages:
      dependency_groups = [
        _dash_renderer._js_dist_dependencies,
        _dash_renderer._js_dist,
        dcc._js_dist,
        dash_table._js_dist,
        html._js_dist,
        self.__app.scripts.get_all_scripts(),
        self.__app.css.get_all_css()
      ]

      self.__packages: list[PackagePaths] = []
      for group in dependency_groups:
        for dependencies in group:
          self.__add_relative_package_paths(dependencies, 'prod')

    return self.__packages
  

  def __add_relative_package_paths(self, dependencies: dict, stage: str) -> None:
    if 'relative_package_path' not in dependencies:
      return
    
    if isinstance(dependencies['relative_package_path'], str):
      namespace = dependencies['namespace']
      is_dynamic = dependencies.get('dynamic', False)
      relative_package_path = dependencies['relative_package_path']
      is_async = dependencies.get('async', False) in [True, 'eager']
      package = os.path.join(namespace, relative_package_path)
      if self.__is_dash_sub_package(package):
        namespace = f"{namespace}.{os.path.split(relative_package_path)[0]}"
      
      self.__packages.append(PackagePaths(
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

      if self.__is_dash_sub_package(package):
        namespace = f"{namespace}.{os.path.split(relative_package_path)[0]}"
    
    self.__packages.append(PackagePaths(
      is_async=is_async,
      namespace=namespace,
      is_dynamic=is_dynamic,
      relative_paths=paths
    ))


  def __is_dash_sub_package(self, dependency: str) -> bool:
    for path in self.dash_sub_package_paths:
      if dependency.startswith(path):
        return True
    
    return False


class DashAssetsBundler:
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


  def __init__(self, app: Dash, client: FlaskClient):
    self.__app = app
    self.__client = client
    self.__static_path = os.environ['OPEN_DASH_STATIC_PATH']
    self.__open_dash_path = os.path.abspath(os.path.join(self.__static_path, '..'))

    self.__default_root_object = None
    self.__dependency_lookup = DependencyLookup(app)
    self.__additional_bundles: dict[str, MiscBundle] = {}
    self.__cloud_front_behaviors: list[CloudFrontBehavior] = []

    origin_path_prefix = self.__app.config.get('url_base_pathname') or '/'
    if origin_path_prefix.startswith('/'):
      origin_path_prefix = origin_path_prefix.replace('/', '', 1)
    
    if origin_path_prefix.endswith('/'):
      origin_path_prefix = origin_path_prefix[0:len(origin_path_prefix) - 1]
    
    if origin_path_prefix:
      url_base_components = origin_path_prefix.split('/')
      self.__static_path = os.path.join(self.__static_path, *url_base_components)
    
    self.__origins: dict[str, S3Origin | FunctionOrigin] = {
      's3': S3Origin(
        copy=[],
        mimetypes={},
        origin_path_prefix=origin_path_prefix,
      ),
    }


  def bundle_assets(self) -> None:
    # Create the static directory with the base URL, if it does not exist.
    os.makedirs(self.__static_path, exist_ok=True)

    self.__export_js_dependencies()

    if os.environ['OPEN_DASH_EXPORT_STATIC'] == '1':
      self.__export_static_pages()
    
    if 'OPEN_DASH_WARMER_FUNCTION_PATH' in os.environ:
      # The warmer function was already copied to the server functions directory so we just need to add it to the
      # output as an additional bundle.
      self.__additional_bundles['warmer'] = MiscBundle(
        handler='index.handler',
        bundle=os.path.join('.open-dash', os.environ['OPEN_DASH_WARMER_FUNCTION_PATH'].split('.open-dash/')[-1]),
      )

    if 'OPEN_DASH_ASSETS_PATH' in os.environ:
      self.__copy_assets_path()
    
    if 'OPEN_DASH_SOURCE_DATA_PATH' in os.environ:
      BundlerUtils.copy_directory_contents(
        os.environ['OPEN_DASH_SOURCE_DATA_PATH'],
        os.path.join(self.__open_dash_path, 'data'),
        []
      )

      self.__additional_bundles['dataPath'] = MiscBundle(
        bundle=os.path.join('.open-dash', 'data'),
      )
    
    self.__serialize_output_to_json()
  
  
  def __serialize_output_to_json(self) -> None:
    self.__origins['default'] = FunctionOrigin(
      handler='index.handler',
      dockerfile='Dockerfile',
      bundle=os.path.join('.open-dash', os.environ['OPEN_DASH_SERVER_FUNCTIONS_PATH'].split('.open-dash/')[-1]),
    )
    self.__cloud_front_behaviors.append(CloudFrontBehavior(
      origin='default',
      pattern='*',
    ))

    output = OpenDashOutput(
      additional_bundles=self.__additional_bundles,
      global_fingerprint=global_fingerprint if os.environ['OPEN_DASH_FINGERPRINT_METHOD'] == 'global' else None,
      cloud_front_config=CloudFrontConfig(
        origins=self.__origins,
        behaviors=self.__cloud_front_behaviors,
        default_root_object=self.__default_root_object,
      ),
    )

    with open(os.path.join(self.__open_dash_path, 'open-dash.output.json'), 'w') as f:
      f.write(output.to_json())


  def __export_static_pages(self) -> None:
    self.__extract_static_pages_from_server()

    if self.__origins['s3'].find_copy(target_prefix='_dash-update-component/'):
      self.__cloud_front_behaviors.append(CloudFrontBehavior(
        origin='s3',
        pattern=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, '_dash-update-component')
      ))
    
    self.__cloud_front_behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, '_dash-layout'),
    ))
    self.__cloud_front_behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, '_dash-dependencies'),
    ))

    index_item = self.__origins['s3'].find_copy(target_suffix='index.html')
    if index_item:
      self.__default_root_object = index_item.target
  

  """
  Copy JavaScript dependencies from Python static-packages and the app's assets directory to the static directory.
  """
  def __export_js_dependencies(self) -> None:
    components_path = os.path.join(
      self.__static_path,
      BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, '_dash-component-suites')
    )
  
    for pkg in self.__dependency_lookup.get_internal_dependencies():
      namespace_prefix = os.path.join(*f'{pkg.namespace}.'.split('.'))
      namespace_path = os.path.dirname(sys.modules[pkg.namespace].__file__)
      for dependency_path in pkg.relative_paths:
        source = os.path.join(namespace_path, dependency_path.replace(namespace_prefix, ''))
        if not os.path.exists(source):
          print(f'Warning: Dependency {source} not found, skipping...')
          continue

        target_directory = os.path.dirname(os.path.join(components_path, dependency_path))
        os.makedirs(target_directory, exist_ok=True)

        filename = BundlerUtils.asset_file_name(
          self.__dependency_lookup.namespace_version(pkg.namespace), 
          dependency_path,
          source
        )
        shutil.copy2(source, os.path.join(target_directory, filename))

        if pkg.is_dynamic or pkg.is_async:
          # Copy the original filename if the dependency is dynamic or async because the client can potentially request 
          # the unfingerprinted file.
          # 
          # NOTE: This creates a duplicate file in the assets directory so we should investigate if there is a way to
          #      determine ahead of time if the client will request the fingerprinted or unfingerprinted file.
          shutil.copy2(source, os.path.join(target_directory, os.path.basename(dependency_path)))
    
    self.__origins['s3'].copy.append(S3OriginCopy(
      source=os.path.join('.open-dash', 'static', '_dash-component-suites'),
      target=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, '_dash-component-suites'),
    ))
    self.__cloud_front_behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, '_dash-component-suites/*'),
    ))

  
  """
  Export contents of the application's pages/ directory into the static folder. Dash fetches these pages by POSTing a
  request to the /_dash-update-component route with the pathname input set to the relative path of the page. The 
  response is a JSON object containing the layout and dependencies of the page. We cache the response to a file in the
  static/_dash-update-component directory to avoid calls to the Dash server.
  
  NOTE: Do not use the contents of the static/_dash-update-component directory if your site uses cookies to display 
        different content for the same path. The cached files will not reflect the content that would be returned by 
        the server.
  """
  def __export_registry_pages(
    self,
    *,
    url_base: str,
    copy_source_prefix: str = None,
    copy_target_prefix: str = None,
  ) -> None:
    has_custom_404 = False
    target_directory = os.path.join(self.__static_path, '_dash-update-component')
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

      params = self.update_components_params.copy()
      # Note that the value of the pathname input is the relative path of the page which includes the base url.
      params['inputs'][0]['value'] = page.get('relative_path')
      self.__cache_json_request(
        url=f'{url_base}_dash-update-component',
        target_file_path=os.path.join(target_directory, page_path),
        method=RequestMethod.POST,
        params=params,
        copy_source_prefix=copy_source_prefix,
        copy_target_prefix=copy_target_prefix,
      )
    
    if not has_custom_404:
      self.__cache_json_request(
        url=f'{url_base}_dash-update-component',
        target_file_path=os.path.join(target_directory, '404'),
        method=RequestMethod.POST,
        params=self.update_components_params,
        copy_source_prefix=copy_source_prefix,
        copy_target_prefix=copy_target_prefix,
      )
  
  
  def __cache_json_request(
    self,
    *,
    url: str,
    target_file_path: str,
    method: RequestMethod,
    params: dict,
    copy_source_prefix: str = None,
    copy_target_prefix: str = None,
  ):
    response = self.__client.get(url) if method == RequestMethod.GET else self.__client.post(url, json=params)
    if response.status_code != 200:
      return 
    
    with open(target_file_path, 'w') as f:
      f.write(response.data.decode('UTF-8'))

    page_suffix = os.path.basename(target_file_path)
    self.__origins['s3'].copy.append(S3OriginCopy(
      target=BundlerUtils.join_path(copy_target_prefix, page_suffix),
      source=os.path.join(copy_source_prefix, page_suffix),
    ))
    self.__origins['s3'].mimetypes[BundlerUtils.join_path(copy_target_prefix, page_suffix)] = 'application/json'


  def __copy_assets_path(self) -> None:
    # Copy the assets directory into the .open-dash/static directory. Note that the server functions directory
    # has a copy of the assets directory as well, if it exists, to ensure that the assets are available to the
    # fallback server function.
    BundlerUtils.copy_directory_contents(
      os.environ['OPEN_DASH_ASSETS_PATH'],
      os.path.join(self.__static_path, BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, 'assets')),
      []
    )

    self.__cloud_front_behaviors.append(CloudFrontBehavior(
      origin='s3',
      pattern=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, 'assets/*'),
    ))
    self.__origins['s3'].copy.append(S3OriginCopy(
      source=os.path.join('.open-dash', 'static', 'assets'),
      target=BundlerUtils.join_path(self.__origins['s3'].origin_path_prefix, 'assets'),
    ))
  

  """
  Exports index.html and other static pages to the static directory.

  Dash apps call the /_dash-layout and /_dash-dependencies routes from the client side to retrieve the layout and 
  additional dependencies. Since these values do not change after the app is built, we can write them to the static 
  directory to avoid unnecessary calls to the Dash server.

  If this is a multi-page application, we also export the /_dash-update-component route for each page to the static
  directory. This is only done for pages assumed to be static, i.e. pages that do not have path variables. If your site
  uses cookies to display different content for the same path, you should to ignore contents of the static directory.
  """
  def __extract_static_pages_from_server(self) -> S3Origin:
    url_base = self.__app.config.get('url_base_pathname')
    copy_source_prefix = os.path.join('.open-dash', 'static')
    if url_base is None:
      url_base = '/'
    else:
      url_base_components = url_base.split('/')[1:]
      copy_source_prefix = os.path.join(copy_source_prefix, *url_base_components)
    
    copy_target_prefix = url_base.replace('/', '', 1) if url_base.startswith('/') else None
    
    # Capture index.html and write it to static directory to optionally make it the CloudFront default object.
    # Note that the default fingerprint for all static files matches the index.html references.
    with open(os.path.join(self.__static_path, 'index.html'), 'w') as f:
      index_html = self.__client.get(url_base).data.decode('UTF-8')
      f.write(index_html.replace('http://localhost', f'https://{os.environ["OPEN_DASH_DOMAIN_NAME"]}'))
      self.__origins['s3'].copy.append(S3OriginCopy(
        source=os.path.join(copy_source_prefix, 'index.html'),
        target=BundlerUtils.join_path(copy_target_prefix, 'index.html'),
      ))
    
    self.__cache_json_request(
      url=f'{url_base}_dash-layout',
      target_file_path=os.path.join(self.__static_path, '_dash-layout'),
      method=RequestMethod.GET,
      params={},
      copy_source_prefix=copy_source_prefix,
      copy_target_prefix=copy_target_prefix,
    )
    
    self.__cache_json_request(
      url=f'{url_base}_dash-dependencies',
      target_file_path=os.path.join(self.__static_path, '_dash-dependencies'),
      method=RequestMethod.GET,
      params={},
      copy_source_prefix=copy_source_prefix,
      copy_target_prefix=copy_target_prefix,
    )

    if page_registry:
      self.__export_registry_pages(
        url_base=url_base,
        copy_source_prefix=copy_source_prefix,
        copy_target_prefix=copy_target_prefix,
      )


if __name__ == '__main__':
  with app.server.test_request_context():
    with app.server.test_client() as client:
      DashAssetsBundler(app, client).bundle_assets()
