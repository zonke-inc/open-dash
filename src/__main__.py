#!python

import argparse
from os import path
import bundle


parser = argparse.ArgumentParser(description='Bundles Dash assets for deployment on AWS.')
subparsers = parser.add_subparsers(dest='command', required=True)

bundle_parser = subparsers.add_parser('bundle', help='Bundle of Dash assets for deployment.')
bundle_parser.add_argument(
  '--source',
  '-s',
  type=str,
  required=True,
  help='The path to the source directory containing the Dash application.'
)
bundle_parser.add_argument(
  '--exclude-dirs',
  '-e',
  type=str,
  required=False,
  help='Comma-separated list of directories to exclude from the target bundle. Directories should be immediate children of the source directory.'
)
bundle_parser.add_argument(
  '--include-warmer',
  '-w',
  type=bool,
  required=False,
  help='Whether to include a lambda warmer function in the bundle.'
)

def main():
  args = parser.parse_args()

  if args.command == 'bundle':
    if not args.source:
      print('Error: --source/-s argument is required.')
      return

    if not path.exists(args.source):
      print(f'Error: Source directory {args.source} does not exist.')
      return

    if not path.exists(path.join(args.source, 'app.py')):
      print(f'Error: Source directory {args.source} does not contain an app.py file.')
      return

    if not path.exists(path.join(args.source, 'requirements.txt')):
      print(f'Error: Source directory {args.source} does not contain a requirements.txt file.')
      return

    excluded_directories = []
    if args.exclude_dirs:
      excluded_directories = args.exclude_dirs.split(',')
    
    include_warmer = args.include_warmer if args.include_warmer else False
    bundle.create(args.source, excluded_directories, include_warmer)

    print('Bundle complete.')
