import json
import os
import subprocess

from opendash import bundle
from opendash.config import Config, FingerPrint, FingerPrintType
from unittest import TestCase


class IntegrationTestBase(TestCase):
  def __init__(
    self,
    method_name: str,
    *,
    application_name: str,
    is_lambda_build: bool = False,
    data_path: str = None
  ):
    super().__init__(method_name)

    opendash_path = os.path.abspath(os.path.join(os.path.basename(__file__), '..'))
    
    self._venv_path = os.path.join(opendash_path, f'.venv-{application_name}')
    self._output_path = os.path.join(opendash_path, f'output-{application_name}')
    self._source_path = os.path.join(opendash_path, 'examples', application_name)

    self._config = Config(
      export_static=True,
      data_path=data_path,
      excluded_directories=[],
      domain_name='localhost',
      source_path=self._source_path,
      include_warmer=is_lambda_build,
      virtualenv_path=self._venv_path,
      target_base_path=self._output_path,
      fingerprint=FingerPrint(
        include_version=True,
        method=FingerPrintType.LAST_MODIFIED
      )
    )

  @classmethod
  def setUpClass(cls):
    self = cls()
    result = subprocess.run(
      ['python3', '-m', 'venv', self._venv_path],
      text=True,
      env=os.environ,
      capture_output=True,
    )
    print(result.stdout)

    bundle.create(self._config)

  def validate_output_folder(self, fixture_path: str):
    with open(fixture_path, 'r') as file:
      fixture = json.load(file)

      for filepath in fixture['included']:
        self.assertTrue(
          os.path.exists(os.path.join(self._output_path, filepath)),
          f'{filepath} is missing from the output folder.'
        )
      
      for filepath in fixture['excluded']:
        self.assertFalse(
          os.path.exists(os.path.join(self._output_path, filepath)),
          f'{filepath} should not be in the output folder.'
        )
  
  def validate_open_dash_output_json(self, fixture_path: str):
    with open(fixture_path, 'r') as fixture_file:
      fixture = json.load(fixture_file)

      with open(os.path.join(self._output_path, '.open-dash', 'open-dash.output.json'), 'r') as output_file:
        open_dash_output = json.load(output_file)

        self.assertEqual(
          fixture['defaultRootObject'],
          open_dash_output['cloudFrontConfig']['defaultRootObject'],
          'Default root object does not match.'
        )
        self.__validate_data_path(fixture['includesDataPath'], open_dash_output)
        self.__validate_behavior_patterns('s3', fixture['s3BehaviorPatterns'], open_dash_output)
        self.__validate_behavior_patterns('default', fixture['defaultBehaviorPatterns'], open_dash_output)
        self.__validate_mimetypes(fixture['mimetypes'], open_dash_output)

  @classmethod
  def tearDownClass(cls):
    self = cls()
    if os.path.exists(self._venv_path):
      result = subprocess.run(
        ['rm', '-rf', self._venv_path],
        text=True,
        env=os.environ,
        capture_output=True,
      )
      print(result.stdout)

    if os.path.exists(self._output_path):
      result = subprocess.run(
        ['rm', '-rf', self._output_path],
        text=True,
        env=os.environ,
        capture_output=True,
      )
      print(result.stdout)

  def __validate_mimetypes(self, expected_mimetypes: dict[str, str], open_dash_output: dict):
    for file, mimetype in expected_mimetypes.items():
      self.assertEqual(
        mimetype,
        open_dash_output['cloudFrontConfig']['origins']['s3']['mimetypes'].get(file, None),
        f'Mimetypes do not match for {file}.'
      )

  def __validate_behavior_patterns(self, origin: str, expected_patterns: list[str], open_dash_output: dict):
    current_patterns = []
    for pattern in open_dash_output['cloudFrontConfig']['behaviors']:
      if pattern['origin'] == origin:
        current_patterns.append(pattern['pattern'])

    current_patterns.sort()
    expected_patterns.sort()

    self.assertListEqual(
      expected_patterns,
      current_patterns,
      'Behavior patterns do not match.'
    )
  
  def __validate_data_path(self, includes_data_path: bool, open_dash_output: dict):
    if includes_data_path:
      self.assertTrue(
        'dataPath' in open_dash_output['additionalBundles'],
        '.open-dash/data is missing from the output folder.'
      )
    else:
      self.assertFalse(
        'dataPath' in open_dash_output['additionalBundles'],
        '.open-dash/data should not be in the output folder.'
      )
