import os

from tests.integration.base import IntegrationTestBase


class MultiPageStaticTest(IntegrationTestBase):
  def __init__(self, method_name: str = 'test_expected_files_created'):
    super().__init__(
      method_name,
      application_name='multi-page-static',
      data_path=os.path.join('multi-page-static', 'data')
    )

  def test_expected_files_created(self):
    self.validate_output_folder(
      os.path.join(os.path.dirname(os.path.realpath(__file__)), 'fixtures', 'layout', 'multi-page-static.json')
    )
  
  def test_open_dash_output_json(self):
    self.validate_open_dash_output_json(
      os.path.join(os.path.dirname(os.path.realpath(__file__)), 'fixtures', 'output-config', 'multi-page-static.json')
    )
