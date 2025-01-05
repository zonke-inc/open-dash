from dataclasses import dataclass
import json


@dataclass(kw_only=True)
class CloudFrontBehavior:
  """
  The path pattern to match for this behavior.
  """
  pattern: str

  """
  The origin to associate with this behavior.
  """
  origin: str


@dataclass(kw_only=True)
class S3OriginCopy:
  """
  The source path to copy from.
  """
  source: str

  """
  The target path to copy to.
  """
  target: str


@dataclass(kw_only=True)
class S3Origin:
  """
  The type of origin. Should be s3.
  """
  type: str = 's3'

  """
  The base path to copy to in the S3 bucket.
  """
  origin_path_prefix: str

  """
  Paths to copy from the OpenDash output to the S3 bucket.
  """
  copy: list[S3OriginCopy]

  """
  A dictionary of mimetypes to associate with some objects in the S3 bucket. Use this dictionary to set the Content-Type
  metadata for objects in the S3 bucket. The key is the full path to the object in the S3 bucket, and the value is the
  mimetype to associate with the object.
  
  NOTE: Not all objects will be in this dictionary. Only objects without an extension will be included.
  """
  mimetypes: dict[str, str]

  def to_dict(self) -> dict:
    return {
      'type': self.type,
      'mimetypes': self.mimetypes,
      'originPathPrefix': self.origin_path_prefix,
      'copy': [copy.__dict__ for copy in self.copy],
    }

  def find_copy(self, *, target_suffix: str = None, target_prefix: str = None) -> S3OriginCopy:
    for copy in self.copy:
      if target_suffix and copy.target.endswith(target_suffix):
        return copy
      
      if target_prefix and copy.target.startswith(target_prefix):
        return copy
      
    return None


@dataclass(kw_only=True)
class FunctionOrigin:
  """
  The ARN of the Lambda function to associate with the CloudFront distribution.
  """
  type: str = 'function'

  """
  The lambda function's handler.
  """
  handler: str

  """
  The path to the lambda function's code bundle.
  """
  bundle: str

  """
  The path to the lambda function's Dockerfile.
  """
  dockerfile: str = None

  def to_dict(self) -> dict:
    return self.__dict__


@dataclass(kw_only=True)
class MiscBundle:
  """
  The path to the miscellaneous bundle.
  """
  bundle: str

  """
  The lambda function's handler.
  """
  handler: str = None


@dataclass(kw_only=True)
class CloudFrontConfig:
  """
  The dictionary of origins to associate with the CloudFront distribution.
  """
  origins: dict[str, S3Origin | FunctionOrigin]

  """
  The list of behaviors to associate with the CloudFront distribution.
  """
  behaviors: list[CloudFrontBehavior]

  """
  The default root object for the CloudFront distribution.
  """
  default_root_object: str = None

  def to_dict(self) -> dict:
    return {
      'defaultRootObject': self.default_root_object or '',
      'behaviors': [behavior.__dict__ for behavior in self.behaviors],
      'origins': {key: origin.to_dict() for key, origin in self.origins.items()},
    }


@dataclass(kw_only=True)
class OpenDashOutput:
  """
  The global fingerprint, if used in the OpenDash output.
  """
  global_fingerprint: str = None

  """
  Output CloudFront configuration for the OpenDash bundle.
  """
  cloud_front_config: CloudFrontConfig

  """
  The dictionary of miscellaneous bundles to associate with the OpenDash output.
  """
  additional_bundles: dict[str, MiscBundle]

  def to_json(self) -> str:
    return json.dumps({
      'globalFingerprint': self.global_fingerprint or '',
      'cloudFrontConfig': self.cloud_front_config.to_dict(),
      'additionalBundles': {key: bundle.__dict__ for key, bundle in self.additional_bundles.items()},
    }, sort_keys=True, indent=2)
