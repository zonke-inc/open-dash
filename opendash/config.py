from dataclasses import dataclass
from enum import Enum
import json
import os
import sys
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
  Whether to include a warmer function in the output bundle.
  """
  include_warmer: bool
  
  """
  The fingerprint configuration for the output bundle.
  """
  fingerprint: FingerPrint
  
  """
  Whether to include an index.html file in the output bundle.
  """
  include_index_html: bool
  
  """
  Directories to exclude from the output bundle.
  """
  excluded_directories: list[str]

  """
  Optional - The path to the virtual environment directory. If not provided, the system Python interpreter is used.
  """
  virtualenv_path: Optional[str]
  
  """
  Creates a Config instance from an open-dash.config.json file. open-dash.config.json file structure:
  {
    "warmer": true,
    "index-html": true,
    "venv-path": "path/to/venv",
    "source-path": "path/to/source",
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

        return Config(
          fingerprint=fingerprint,
          virtualenv_path=data.get('venv-path'),
          exclude_warmer=data.get('warmer', True),
          excluded_directories=data.get('exclude', []),
          include_index_html=data.get('index-html', False),
          source_path=os.path.abspath(data.get('source-path', os.getcwd()))
        )
    
    print(f'OpenDash config not found at {path}. Using system defaults.')
    
    return Config(
      exclude=[],
      include_warmer=False,
      source_path=os.getcwd(),
      include_index_html=False,
      fingerprint=FingerPrint(
        include_version=True,
        method=FingerPrintType.LAST_MODIFIED
      )
    )
