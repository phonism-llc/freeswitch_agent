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
        print("Response Content: ", sep="", end="\n")
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
        print('The response data: ', phonism_integration_data, sep="\n", end="\n\n", flush=True)
        sys.exit(1)

    if verbose > 1:
        print("Integration data: ")
        pprint(phonism_integration_data, width=120)
        print('')

    ## Now get the FreeSwitch users, and parse them into a usable format.
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

    ## Group like fs user extension columns together.
    processed = []
    grouped_fs_user_list = []
    for i, user_dict in enumerate(fs_user_list):
        # Don't process the users in fs_user_list more than once.
        if user_dict['userid'] in processed:
            continue

        # Find all matching users in fs_cli user list
        similar_users = list(filter(lambda fs_user: fs_user['userid'] == user_dict['userid'], fs_user_list))

        if len(similar_users) == 1:
            # If there is only 1, append it to the grouped_fs_user_list
            grouped_fs_user_list.append(similar_users[0])
            processed.append(similar_users[0]['userid'])
        elif len(similar_users) > 1:
            # Else If, there is more than one, group the column values into lists.
            grouped_user_dict = defaultdict(list)
            for key, value in [(k, v) for udict in similar_users for (k, v) in udict.items()]:
                if value not in list(grouped_user_dict[key]) :
                    grouped_user_dict[key].append(value)

            # Loop back through the grouped_user_dict and convert any list 
            # that only has one element into a string. 
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

    # The page number to request from the Phonism API.
    page_num = 1 
    # Conditional to keep the while loop going.       
    keep_going = True  
    # List of extensions not to create when we loop through the fs_user_list after the while loop.
    updated_phonism_extensions = []

    ## Keep requesting Phonism extension data until there is no more...
    while keep_going == True:
        ## Get Phonism extension data
        extensions_api_url = endpoint + 'extensions?limit=2&page={0}&tenant_id={1}'.format(page_num, tenant_id)

        if verbose > 2:
            print('extensions_api_url: ', extensions_api_url)

        response = requests.get(extensions_api_url, headers=headers)
        phonism_extension_data = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='get')

        if True or verbose > 1:
            print('Extension data: ', end="\n")
            pprint(phonism_extension_data, width=120)
            print('')

        try:
            if len(phonism_extension_data) == 0:
                keep_going = False
                break
        except (TypeError, ValueError):
            print('Could not obtain phonism_extension_data... ', phonism_extension_data, sep="\n", end="\n\n", flush=True)
            sys.exit(1)

        ## Loop through phonism_extension_data and do stuff depending on whether you find it in fs_user_list
        for pi, ph_ext_dict in enumerate(phonism_extension_data):
            fs_user_found = False
            found_fs_user_dict = {}
            for fi, fs_user_dict in enumerate(fs_user_list):
                if str(fs_user_dict['userid']) == str(ph_ext_dict['extension']):
                    fs_user_found = True
                    found_fs_user_dict = dict(fs_user_dict)

            if fs_user_found: 
                # If the Phonism extension is found in FreeSwitch, update it.    
                
                # Add the Phonism extension to the updated list so that it is not created.
                updated_phonism_extensions.append(found_fs_user_dict['userid'])

                # Create the update url
                extensions_api_url = endpoint + 'extensions/{0}'.format(ph_ext_dict['id'])

                # Update Data:
                put_data = {
                    'tenant_id': tenant_id,
                    'extension': found_fs_user_dict['userid'],
                    'secret': found_fs_user_dict['user_password']
                }

                # Make Http REST request. Die on response error.
                response = requests.put(extensions_api_url, data=put_data, headers=headers)
                updated_extension = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='put')

                if verbose > 0:
                    print("Updated extension \"{0}\" in Phonism.".format(updated_extension['extension']))

            else: 
                # Else, delete the Phonism extension.

                # Create the delete url
                extensions_api_url = endpoint + 'extensions/{0}'.format(ph_ext_dict['id'])

                # Make Http REST request. Die on response error.
                response = requests.delete(extensions_api_url, headers=headers)
                deleted_extension = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='delete')

                if verbose > 0:
                    print("Deleted extension id #{0} from Phonism.".format(deleted_extension['id']))

        page_no += 1 


    ## Loop through fs_user_list and do stuff depending on whether you find it in phonism_extension_data
    for fi, fs_user_dict in enumerate(fs_user_list):
        # If not in the updated_phonism_extensions list, create it.
        if fs_user_dict['userid'] not in updated_phonism_extensions:
            # Create the insert url.
            extensions_api_url = endpoint + 'extensions'

            # Insert Data:
            post_data = {
                'tenant_id': tenant_id,
                'extension': fs_user_dict['userid'],
                'secret': fs_user_dict['user_password']
            }

            # Make Http REST request. Die on response error.
            response = requests.post(extensions_api_url, data=post_data, headers=headers)
            created_extension = processRequestsResponse(response=response, request_url=extensions_api_url, request_verb='post')

            if verbose > 0:
                print("Created extension \"{0}\" in Phonism.".format(created_extension['extension']))

    
# Done! 
sys.exit(0)

