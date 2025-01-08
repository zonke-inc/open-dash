#!python

import argparse
from opendash import bundle
import os
import sys

from opendash.config import Config


parser = argparse.ArgumentParser(description='Bundles Dash assets for deployment on AWS.')
subparsers = parser.add_subparsers(dest='command', required=True)

bundle_parser = subparsers.add_parser('bundle', help='Bundle Dash assets for deployment.')
bundle_parser.add_argument(
  '--config-path',
  '-c',
  type=str,
  required=False,
  help='Path to the open-dash.config.json configuration file.'
)


def main():
  args = parser.parse_args()

  if args.command == 'bundle':
    config = Config.from_path(args.config_path)

    if not os.path.exists(os.path.join(config.source_path, 'app.py')):
      print(f'Error: Source directory {config.source_path} does not contain an app.py file.')
      sys.exit(1)

    if not os.path.exists(os.path.join(config.source_path, 'requirements.txt')):
      print(f'Error: Source directory {config.source_path} does not contain a requirements.txt file.')
      sys.exit(1)
    
    bundle.create(config)

    print('Bundle complete.')
  
  sys.exit(0)

if __name__ == '__main__':
  main()
