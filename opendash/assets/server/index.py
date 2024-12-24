import awsgi
import os

# The create_app function should return a Dash instance.
from app import create_app


def get_server():
    global server_cache
    if server_cache is None:
        server_cache = create_app().server
    return server_cache

def handler(event, context):
    if 'requestContext' not in event or not event['requestContext'] or not event['requestContext'].get('http'):
        # This is a warmer event. Ignore it.
        return {
            'statusCode': 200,
        }
    
    if 'DOMAIN_NAME' not in os.environ:
        raise ValueError('DOMAIN_NAME environment variable not set')

    domain_name = os.environ.get('DOMAIN_NAME')
    path = event['requestContext']['http']['path']

    event['path'] = path
    event['requestContext']['http']['path'] = path
    event['httpMethod'] = event['requestContext']['http']['method']
    event['queryStringParameters'] = event.get('queryStringParameters', {})

    event['headers']['host'] = domain_name
    event['requestContext']['domainName'] = domain_name
    event['requestContext']['domainPrefix'] = domain_name.split('.')[0]

    return awsgi.response(get_server(), event, context)
