#!/usr/bin/env python

import logging
import os
import sys
import time
import argparse
import httplib2
from oauth2client.client import flow_from_clientsecrets
from oauth2client.file import Storage
from oauth2client import tools
from oauth2client.tools import run_flow
from apiclient.discovery import build

# New instance properties
DEFAULT_MACHINE_TYPE = 'n1-standard-8'
DEFAULT_NETWORK = 'default'
DEFAULT_SERVICE_EMAIL = 'default'
DEFAULT_SCOPES = ['https://www.googleapis.com/auth/devstorage.full_control',
                  'https://www.googleapis.com/auth/compute']

# New root persistent disk properties
DEFAULT_SNAPSHOT = 'your-snapshot-base-image'

DEFAULT_ZONE = 'us-central1-b'
API_VERSION = 'v1'
GCE_URL = 'https://www.googleapis.com/compute/%s/projects/' % (API_VERSION)
PROJECT_ID = 'your-project-id-here'
CLIENT_SECRETS = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'client_secrets.json')
OAUTH2_STORAGE = os.path.join(os.path.abspath(os.path.dirname(__file__)), 'oauth2.dat')
GCE_SCOPE = 'https://www.googleapis.com/auth/compute'

def main(argv):
  logging.basicConfig(level=logging.INFO)

  # Print to stderr because Jenkins slave output is funky.
  print >> sys.stderr, 'Starting script...'

  parser = argparse.ArgumentParser(
    description=__doc__,
    formatter_class=argparse.RawDescriptionHelpFormatter,
    parents=[tools.argparser])
  parser.add_argument('action', choices=['up', 'down', 'list'])
  parser.add_argument('--instance_name', required=False)

  # Parse the command-line flags.
  flags = parser.parse_args(argv[1:])
  if not flags.instance_name and flags.action in ['up', 'down']:
    parser.print_help()
    sys.exit()
  instance_name = flags.instance_name

  # Perform OAuth 2.0 authorization.
  flow = flow_from_clientsecrets(CLIENT_SECRETS, scope=GCE_SCOPE)
  storage = Storage(OAUTH2_STORAGE)
  credentials = storage.get()

  print >> sys.stderr, 'Checking for stored OAuth2 credentials...'
  print >> sys.stderr, 'If slave startup hangs here, you probably need to manually login and run the slave.up script once to populate oauth2.dat.'

  if credentials is None or credentials.invalid:
    credentials = run_flow(flow, storage, flags)
  http = httplib2.Http()
  auth_http = credentials.authorize(http)

  print >> sys.stderr, 'Got credentials!'

  # Build the service
  gce_service = build('compute', API_VERSION)
  project_url = '%s%s' % (GCE_URL, PROJECT_ID)

  # Construct URLs
  zone_url = '%s/zones/%s' % (project_url, DEFAULT_ZONE)
  disk_source_url = '%s/zones/%s/disks/%s' % (
    project_url, DEFAULT_ZONE, instance_name)  # Disk name matches instance name.
  machine_type_url = '%s/zones/%s/machineTypes/%s' % (
    project_url, DEFAULT_ZONE, DEFAULT_MACHINE_TYPE)
  network_url = '%s/global/networks/%s' % (project_url, DEFAULT_NETWORK)

  def list_instances():
    # List instances
    request = gce_service.instances().list(project=PROJECT_ID, filter=None, zone=DEFAULT_ZONE)
    response = request.execute(http=auth_http)
    if response and 'items' in response:
      instances = response['items']
      return instances
    else:
      return []

  def up():
    # Skip startup if slave is already up.
    if instance_name in [instance['name'] for instance in list_instances()]:
      sys.exit('Slave "%s" already exists.' % instance_name)

    print_instances()

    # Construct the request body
    instance = {
      'name': instance_name,
      'machineType': machine_type_url,
      'disks': [{
        'type': 'PERSISTENT',
        'boot': 'true',
        'mode': 'READ_WRITE',
        'deviceName': instance_name,
        'zone': zone_url,
        'source': disk_source_url,
        'autoDelete': 'false',
      }],
      'networkInterfaces': [{
        'accessConfigs': [{
          'type': 'ONE_TO_ONE_NAT',
          'name': 'External NAT'
         }],
        'network': network_url,
      }],
      'serviceAccounts': [{
           'email': DEFAULT_SERVICE_EMAIL,
           'scopes': DEFAULT_SCOPES,
      }]
    }

    # Create the instance.
    request = gce_service.instances().insert(
         project=PROJECT_ID, body=instance, zone=DEFAULT_ZONE)
    response = request.execute(http=auth_http)
    response = _blocking_call(gce_service, auth_http, response)
    print >> sys.stderr, response

  def down():
    print_instances()
    request = gce_service.instances().delete(
         project=PROJECT_ID, zone=DEFAULT_ZONE, instance=instance_name)
    response = request.execute(http=auth_http)
    response = _blocking_call(gce_service, auth_http, response)
    print >> sys.stderr, response

  def print_instances():
    print >> sys.stderr
    for instance in list_instances():
      print >> sys.stderr, instance['name']
    print >> sys.stderr

  if flags.action == 'up':
    up()
  elif flags.action == 'down':
    down()
  elif flags.action == 'list':
    print_instances()
  else:
    raise Exception('Invalid action: %s' % flags.action)
  

def _blocking_call(gce_service, auth_http, response):
  """Blocks until the operation status is done for the given operation."""

  status = response['status']
  while status != 'DONE' and response:
    operation_id = response['name']

    # Identify if this is a per-zone resource
    if 'zone' in response:
      zone_name = response['zone'].split('/')[-1]
      request = gce_service.zoneOperations().get(
          project=PROJECT_ID,
          operation=operation_id,
          zone=zone_name)
    else:
      request = gce_service.globalOperations().get(
           project=PROJECT_ID, operation=operation_id)

    response = request.execute(http=auth_http)
    if response:
      status = response['status']
    time.sleep(1)
  return response

if __name__ == '__main__':
  main(sys.argv)
