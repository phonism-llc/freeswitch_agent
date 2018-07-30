#!/usr/bin/env python3
# (C) Phonism, LLC. 2018
# All rights reserved
# Licensed under BSD 3-Clause "New" or "Revised" License (see LICENSE)

import sys
import subprocess
import json
import requests
import argparse
import configparser

from pprint import pprint
from collections import defaultdict

class VAction(argparse.Action):
    def __call__(self, parser, args, values, option_string=None):
        # print('values: {v!r}'.format(v=values))
        if values == None:
            values = '1'
        try:
            values = int(values)
        except ValueError:
            values = values.count('v') + 1
        setattr(args, self.dest, values)

## Global Variables
ini_file = '/opt/phonism/phonism_freeswitch_agent.ini'
company_id = None
tenant_id = None
verbose = 0

## Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('-v', nargs='?', action=VAction, dest='verbose', help='Output verbosity')
args = parser.parse_args(sys.argv[1:])
if args.verbose:
    verbose = args.verbose

## Functions
def getConfig():
    # Get config values from phonism_freeswitch_agent.ini
    config = configparser.ConfigParser()
    config.read(ini_file)

    return (config['phonism']['endpoint'],
            config['phonism']['api_key'])

def processRequestsResponse(response, request_url='', request_verb=''):
    # Try to parse the json. If not json store that too.
    try:
        response_content = json.loads(response.content.decode('utf-8'))
    except ValueError:
        response_content = response.content.decode('utf-8')

    # No 200 response, exit script... 
    if response.status_code != 200:
        print('')
        print("An Http request to Phonism resulted in an error.")
        if request_url:
            print("Request url: ", request_url)
        if request_verb:
            print("Request verb: ", request_verb)
        print("Status Code: ",  response.status_code)
        print("Response Content: ")
        pprint(response_content, width=120, depth=10)
        print('')
        sys.exit(1)

    return response_content

def executeShellCmd(cmd):
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
    output, err = p.communicate()
    p_status = p.wait()

    if int(p_status) > 0:
        print("{0} exit status: {1}".format(cmd, p_status))
        print("error: {0}".format(err))
        sys.exit(1)

    if err:
        print("{0} exit status: {1}".format(cmd, p_status))
        print("error: {0}".format(err))
        sys.exit(1)

    return output.decode("utf-8")

if __name__ == '__main__':
    ## Get the INI values
    endpoint, api_key = getConfig()

    ## Build the headers used in the api requests
    headers = {
        'Content-Type': 'application/json',
        'X-API-KEY': '{0}'.format(api_key)
    }

    ## Contact the Phonism integrations endpoint to see if we have one and it's still active
    integration_api_url = endpoint + 'integrations/mine'

    if verbose > 2:
        print('integration_api_url', integration_api_url)

    response = requests.get(integration_api_url, headers=headers)
    phonism_integration_data = processRequestsResponse(response=response, request_url=integration_api_url, request_verb='get')

    if not phonism_integration_data:
        print('Could not parse \"/integrations/mine\" response data.')

    try:
        tenant_id = int(phonism_integration_data['tenant_id'])
        company_id = int(phonism_integration_data['company_id'])
    except (TypeError, ValueError, KeyError):
        print('There was no tenant_id in the response data.')
        print('Please contact Phonism support for assistance.')
        print("The response:")
        print(phonism_integration_data)
        sys.exit(1)

    if verbose > 1:
        print("Integration data: ")
        pprint(phonism_integration_data, width=120)
        print('')

    ## Get the Phonism extension data
    extensions_api_url = endpoint + 'extensions?limit=100&tenant_id={0}'.format(tenant_id)

    if verbose > 2:
        print('extensions_api_url: ', extensions_api_url)

    response = requests.get(extensions_api_url, headers=headers)
    phonism_extension_data = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='get')

    if verbose > 1:
        print("Extension data: ")
        pprint(phonism_extension_data, width=120)
        print('')

    ## Then get the FreeSwitch users
    cmd = 'fs_cli -x list_users'
    fs_user_data = executeShellCmd(cmd=cmd)
    fs_user_data = fs_user_data.split('\n')

    ## Parse fs_user_data into a list of dictionaries
    col_names = []
    fs_user_list = []
    for i, user_data_string in enumerate(fs_user_data):
        user_data_string = user_data_string.strip()

        if i == 0:
            col_names = list(user_data_string.split('|'))
            continue

        if not col_names:
            print('Could not obtain column names from the FreeSwitch data.')
            sys.exit(1)

        if not user_data_string:
            continue

        if user_data_string == '+OK':
            continue

        user_data_list = list(user_data_string.split('|'))

        user_dict = {}
        for j, col_name in enumerate(col_names):
            try:
                user_dict[col_name] = user_data_list[j]
            except IndexError:
                continue

        fs_user_list.append(user_dict)

    ## Now loop through fs_user_list and lookup the user's password and append it to the user_dict
    for i, user_dict in enumerate(fs_user_list):
        cmd = 'fs_cli -x "user_data {0}@{1} param password"'.format(user_dict['userid'], user_dict['domain'])
        user_password = executeShellCmd(cmd=cmd)
        if user_password:
            user_dict['user_password'] = user_password.strip()

    ## Group like extensions together.
    processed = []
    grouped_fs_user_list = []
    for i, user_dict in enumerate(fs_user_list):
        if user_dict['userid'] in processed:
            continue

        # find all matching users in fs_cli user list
        similar_users = list(filter(lambda fs_user: fs_user['userid'] == user_dict['userid'], fs_user_list))

        if len(similar_users) == 1:
            #  If there is only 1, append it to the grouped_fs_user_list
            grouped_fs_user_list.append(similar_users[0])
            processed.append(similar_users[0]['userid'])
        elif len(similar_users) > 1:
            # Else If, there is more than one, group the like items into lists.
            grouped_user_dict = defaultdict(list)
            for key, value in [(k, v) for udict in similar_users for (k, v) in udict.items()]:
                if value not in list(grouped_user_dict[key]) :
                    grouped_user_dict[key].append(value)

            # Loop back through the grouped_user_dict and convert any list 
            # that only has one element to a string. 
            for key, value in grouped_user_dict.items():
                if len(value) == 1:
                    grouped_user_dict[key] = str(value[0])

            # Append the grouped_user_dict to the grouped_fs_user_list
            grouped_fs_user_list.append(grouped_user_dict)
            processed.append(grouped_user_dict['userid'])

    # Overwrite fs_user_list to be the grouped grouped_fs_user_list
    fs_user_list = grouped_fs_user_list

    if verbose > 1:
        print('FreeSwitch users:')
        pprint(fs_user_list, width=120)
        print('')

    ## Change the headers for this section of the script.
    headers['Content-Type'] = 'application/x-www-form-urlencoded'

    ## Loop through fs_user_list and do stuff depending on whether you find it in phonism_extension_data
    for fi, user_dict in enumerate(fs_user_list):
        ph_ext_found = False
        found_ext_dict = {}
        for pi, ext_dict in enumerate(phonism_extension_data):
            if ext_dict['extension'] == user_dict['userid']:
                ph_ext_found = True
                found_ext_dict = dict(ext_dict)

        if not ph_ext_found:
            # If extension is in FreeSwitch but NOT in Phonism, add to Phonism
            extensions_api_url = endpoint + 'extensions'

            ext_post_data = {
                'tenant_id': tenant_id,
                'extension': user_dict['userid'],
                'secret': user_dict['user_password']
            }

            # Die on response error
            response = requests.post(extensions_api_url, data=ext_post_data, headers=headers)
            created_extension = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='post')

            if verbose > 0:
                print("Created extension \"{0}\" in Phonism.".format(created_extension['extension']))
        else:
            # Else, update Phonism with the current values in FreeSwitch
            if not found_ext_dict:
                print("Trying to update {0} in the Phonism database, but \"Phonism extension data\" is empty...")
                sys.exit(1)

            extensions_api_url = endpoint + 'extensions/{0}'.format(found_ext_dict['id'])

            ext_put_data = {
                'tenant_id': tenant_id,
                'extension': user_dict['userid'],
                'secret': user_dict['user_password']
            }

            # Die on response error
            response = requests.put(extensions_api_url, data=ext_put_data, headers=headers)
            updated_extension = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='put')

            if verbose > 0:
                print("Updated extension \"{0}\" in Phonism.".format(updated_extension['extension']))

    ## Loop through phonism_extension_data and do stuff depending on whether you find it in fs_user_list
    for pi, ext_dict in enumerate(phonism_extension_data):
        fs_ext_found = False
        for fi, user_dict in enumerate(fs_user_list):
            if user_dict['userid'] == ext_dict['extension']:
                fs_ext_found = True

        if not fs_ext_found:
            # If extension is missing from FreeSwitch but is in Phonism, delete from Phonism
            extensions_api_url = endpoint + 'extensions/{0}'.format(ext_dict['id'])

            response = requests.delete(extensions_api_url, headers=headers)
            deleted_extension = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='delete')

            if verbose > 0:
                print("Deleted extension id #{0} from Phonism.".format(deleted_extension['id']))


    sys.exit(0)

