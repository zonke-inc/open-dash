import asyncio
import boto3
import json
import os
import uuid


async def warm_lambdas():
  warm_params_str = os.getenv('WARM_PARAMS')
  if not warm_params_str:
    print('Warmer environment variable WARM_PARAMS not set, exiting...')
    return
  
  tasks = []
  lambda_client = boto3.client('lambda')
  warm_params = json.loads(warm_params_str)
  for warm_param in warm_params:
    if 'FUNCTION_NAME' not in warm_param:
      print('FUNCTION_NAME not found in environment variables, skipping...', warm_param)
      continue

    concurrency = warm_param.get('CONCURRENCY', 1)
    async with asyncio.TaskGroup() as tg:
      for index in range(concurrency):
        tasks.append(tg.create_task(lambda_client.invoke(
          FunctionName=warm_param['FUNCTION_NAME'],
          InvocationType='RequestResponse',
          Payload=json.dumps({
            'index': index,
            'type': 'warmer',
            'concurrency': concurrency,
            'warmerId': str(uuid.uuid4()),
          })
        )))
  
  results = []
  for task in tasks:
    results.append(task.result())

  return results


def handler(event, context):
  results = asyncio.run(warm_lambdas())

  body = json.dumps(results)
  print('Lambda warmer response:', body)

  return {
    'body': body,
    'statusCode': 200,
  }
