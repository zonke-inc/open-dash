from dataclasses import dataclass
from enum import Enum
import json
import os
from typing import Optional, Self


class FingerPrintType(Enum):
  NONE = "none"
  GLOBAL = "global"
  LAST_MODIFIED = "last-modified"


@dataclass(kw_only=True)
class FingerPrint:
  """
  Whether to include the system package version in the fingerprint.
  """
  include_version: bool
  
  """
  The method to use for fingerprinting. Options: "none", "global", "last-modified"
  """
  method: FingerPrintType


@dataclass(kw_only=True)
class Config:
  """
  The path to the application source directory. If not provided, the current working directory is used.
  """
  source_path: str

  """
  The application's domain name. This is used to set the domain name in meta tags in the generated index.html file.
  """
  domain_name: str
  
  """
  Whether to include a warmer function in the output bundle.
  """
  include_warmer: bool
  
  """
  The fingerprint configuration for the output bundle.
  """
  fingerprint: FingerPrint
  
  """
  Whether to export an index.html file and other static files in the output bundle.

  NOTE: This has partial support for multi-page applications. It does not support paths with query strings or path 
        variables. Those should be served by the lambda function that has full server functionality.
  """
  export_static: bool
  
  """
  Directories to exclude from the output bundle.
  """
  excluded_directories: list[str]

  """
  Optional - The path to the data directory.
  """
  data_path: Optional[str]

  """
  Optional - The path to the virtual environment directory. If not provided, the system Python interpreter is used.
  """
  virtualenv_path: Optional[str]

  """
  Optional - The base path to the output directory. If not provided, the source's parent directory is used.
  """
  target_base_path: Optional[str]
  
  """
  Creates a Config instance from an open-dash.config.json file. open-dash.config.json file structure:
  {
    "warmer": true,
    "export-static": true,
    "venv-path": "path/to/venv",
    "data-path": "path/to/data",
    "domain-name": "example.com",
    "source-path": "path/to/source",
    "target-base-path": "path/to/output",
    "exclude": ["dir1", "dir2"],
    "fingerprint": {
      "version": true,
      "method": "last-modified"
    }
  }
  """
  @staticmethod
  def from_path(path: Optional[str] = None) -> Self:
    if not path:
      path = os.path.join(os.getcwd(), 'open-dash.config.json')
    
    if os.path.exists(path):
      with open(path, 'r') as file:
        data = json.load(file)

        if 'fingerprint' in data:
          fingerprint = FingerPrint(
            include_version=data['fingerprint'].get('version', True),
            method=FingerPrintType(data['fingerprint'].get('method', 'last-modified'))
          )
        else:
          # The default fingerprint configuration in Dash's implementation.
          fingerprint = FingerPrint(
            include_version=True,
            method=FingerPrintType.LAST_MODIFIED
          )

        source_path=os.path.abspath(data.get('source-path', os.getcwd()))
        return Config(
          fingerprint=fingerprint,
          source_path=source_path,
          data_path=data.get('data-path'),
          virtualenv_path=data.get('venv-path'),
          include_warmer=data.get('warmer', True),
          excluded_directories=data.get('exclude', []),
          export_static=data.get('export-static', True),
          domain_name=data.get('domain-name', 'localhost'),
          target_base_path=data.get('target-base-path', os.path.abspath(os.path.join(source_path, os.pardir)))
        )
    
    print(f'OpenDash config not found at {path}. Using system defaults.')
    
    return Config(
      data_path=None,
      export_static=True,
      include_warmer=True,
      virtualenv_path=None,
      excluded_directories=[],
      domain_name='localhost',
      source_path=os.getcwd(),
      target_base_path=os.path.abspath(os.path.join(os.getcwd(), os.pardir)),
      fingerprint=FingerPrint(
        include_version=True,
        method=FingerPrintType.LAST_MODIFIED
      )
    )
