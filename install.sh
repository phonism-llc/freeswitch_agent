#!/usr/bin/env bash
# (C) Phonism, LLC. 2018
# All rights reserved
# Licensed under BSD 3-Clause "New" or "Revised" License (see LICENSE)

# Run with:
# PH_API_KEY=ApiKey PH_ENDPOINT=https://app.phonism.com/api/v2/ sudo -E bash -c "$(wget -qO- https://raw.githubusercontent.com/phonism-llc/freeswitch_agent/master/install.sh)"

# Environment Variables 
if [ -n "$PH_API_KEY" ]; then
    API_KEY=$PH_API_KEY
fi
if [ -n "$PH_ENDPOINT" ]; then
    ENDPOINT=$PH_ENDPOINT
fi

## Styles

BOLD=$(tput bold)
RED=$(tput setaf 1)
GREEN=$(tput setaf 2)
YELLOW=$(tput setaf 3)
BLUE=$(tput setaf 4)
PINK=$(tput setaf 5)
CYAN=$(tput setaf 6)
GRAY=$(tput setaf 7)
RESET=$(tput sgr0)


## Variables

DOWNLOAD_HOST="https://raw.githubusercontent.com/phonism-llc/freeswitch_agent/master"
DIR_INSTALL="/opt/phonism"
DIR_CONFIG="/opt/phonism"

ERROR_FLAG=0
PWD=$(pwd)


## Methods

msg_bold(){
    echo -ne "${BOLD}${1}${RESET}"
}
msg_red(){
    echo -ne "${RED}${1}${RESET}"
}
msg_green(){
    echo -ne "${GREEN}${1}${RESET}"
}
nl(){
    echo -ne "\n"
}
cleanup_and_exit(){
    cd $PWD
    exit $1
}


## Check permissions

nl && msg_bold "Checking permissions..." && nl

if [ "$EUID" -ne 0 ]; then
    msg_red "✘ You must run this script with sudo or as root." && nl && nl
    msg_red "Exiting, nothing has been installed." && nl
    cleanup_and_exit 1
else
    msg_green "✔ Running with sudo or as root" && nl && nl
fi


## Check dependencies

msg_bold "Checking dependencies..." && nl

msg_bold "- crontab "
if ! [ -x "$(command -v crontab)" ]; then
    msg_red "✘ crontab is not installed" && nl
    ERROR_FLAG=1
else
    msg_green "✔ crontab is installed" && nl
fi


msg_bold "- FreeSWITCH "
if ! [ -x "$(command -v fs_cli)" ]; then
    msg_red "✘ fs_cli is not installed or not executable" && nl
    ERROR_FLAG=1
else
    # It might be impossible to run even this command without credentials... 
    # Version check probably needs to come later!
    FREESWITCH_VERSION=$(fs_cli -x "version short" 2>&1)
    msg_green "✔ v${FREESWITCH_VERSION} is installed" && nl
fi

msg_bold "- Python "
if ! [ -x "$(command -v python3)" ]; then
    msg_red "✘ python3 is not installed" && nl
    ERROR_FLAG=1
else
    PYTHON_VERSION=$(python3 -V 2>&1 | awk '{ print $2 }' )
    PYTHON_VERSION_REQUIRED="3.4.0"
    if [ "$(printf '%s\n' "$PYTHON_VERSION_REQUIRED" "$PYTHON_VERSION" | sort -V | head -n1)" = "$PYTHON_VERSION_REQUIRED" ]; then 
        msg_green "✔ v${PYTHON_VERSION} is installed" && nl
        PATH_TO_PYTHON=$(which python3)
    else
        msg_red "✘ v${PYTHON_VERSION_REQUIRED} is required, v${PYTHON_VERSION} is installed" && nl
        nl && msg_bold "To install Python 3, run: " && nl
        nl && echo -ne "  sudo apt-get install python3" && nl
        ERROR_FLAG=1
    fi
fi


## Exit if dependencies are insufficient
#  This is done twice, once at this point for Python and 
#  again later to check Python's dependencies

if [[ ERROR_FLAG -eq 1 ]]; then
    nl && msg_red "Correct missing or out-of-date dependencies reported above." && nl
    msg_red "Exiting, nothing has been installed." && nl
    cleanup_and_exit 1
fi


## Install Python specific dependencies

nl && msg_bold "Installing Python dependencies..." && nl
    nl && echo -ne "We will create a standalone virtual Python environment and install required libraries. Would you like to continue? [y/n]:" && nl
    read PYTHON_DECISION

shopt -s nocasematch
if [[ $PYTHON_DECISION != "y" && $PYTHON_DECISION != "yes" ]] ; then
    msg_red "✘ Script cannot be installed without virtual environment." && nl && nl
    msg_red "Exiting, nothing has been installed." && nl
    cleanup_and_exit 1
fi

# install pip 
apt-get install -y python3-pip

# install virtualenv:
apt-get install -y python3-virtualenv

# make and switch to our directory
mkdir -p $DIR_INSTALL
cd $DIR_INSTALL

# create our virtual environment to avoid polluting target machine's python global environment
python3 -m virtualenv -p python3 "phonism_env"

# switch to our virtual environment 
source "$DIR_INSTALL/phonism_env/bin/activate"

# install requests into our virtual environment
pip3 install requests

# exit our virtual environment
deactivate

# store path to python virtual environment
PATH_TO_PYTHON_ENV="${DIR_INSTALL}/phonism_env/bin/python3"

## Check Python dependencies to make sure above worked as expected
#  This is done twice, earlier for high-level dependencies and 
#  again here to check Python's dependencies.

msg_bold "- Python pip3 "
if ! [ -x "$(command -v pip3)" ]; then
    msg_red "✘ pip3 is not installed or not executable" && nl
    nl && msg_bold "To install Python PIP, run: " && nl
    nl && echo -ne "  sudo apt-get install -y python3-pip" && nl
    ERROR_FLAG=1
else
    msg_green "✔ pip3 is installed" && nl
fi

msg_bold "- Python virtualenv "
if ! [ -x "$(command -v $PATH_TO_PYTHON_ENV)" ]; then
    msg_red "✘ virtualenv is not installed or not executable" && nl
    nl && msg_bold "To install Python virtualenv, run: " && nl
    nl && echo -ne "  sudo apt-get install python3-virtualenv" && nl
    ERROR_FLAG=1
else
    msg_green "✔ virtualenv is installed" && nl
fi


## Exit if dependencies are insufficient

if [[ ERROR_FLAG -eq 1 ]]; then
    nl && msg_red "Correct missing or out-of-date dependencies reported above." && nl
    msg_red "Exiting, nothing has been installed." && nl
    cleanup_and_exit 1
fi


## Store API Key and endpoint

if [ -z ${API_KEY+x} ]; then
    nl && msg_bold "Enter your Phonism Integration API Key and press [ENTER]:" && nl
    read INPUT_API_KEY
else
    INPUT_API_KEY=${API_KEY}
fi

if [ -z ${ENDPOINT+x} ]; then
    nl && msg_bold "Enter the Phonism API Endpoint and press [ENTER]:" && nl
    read INPUT_ENDPOINT
else
    INPUT_ENDPOINT=${ENDPOINT}
fi


## Store credentials

nl && msg_bold "Storing settings..." && nl

# make the config directory
mkdir -p $DIR_CONFIG

FILE="${DIR_CONFIG}/phonism_freeswitch_agent.ini"

# create a text file
touch $FILE
chmod 0600 $FILE

/bin/cat <<EOM >$FILE
[phonism]
api_key=${INPUT_API_KEY}
endpoint=${INPUT_ENDPOINT}
EOM

msg_green "✔ Settings stored to: $FILE" && nl


## Download script

nl && msg_bold "Downloading script..." && nl

if [ $(command -v curl) ]; then

    CURL_STATUS=$(curl -s -w %{http_code} -o "phonism_freeswitch_agent.py" "${DOWNLOAD_HOST}/phonism_freeswitch_agent.py")

    if [ $CURL_STATUS == "200" ]; then
        msg_green "✔ Script downloaded to $DIR_INSTALL" && nl
    else
        msg_red "✘ Script could not be downloaded (Error $CURL_STATUS)." && nl && nl
        msg_red "Exiting, nothing has been installed." && nl
        cleanup_and_exit 1
    fi

else

    WGET_STATUS=$(wget --spider -S "${DOWNLOAD_HOST}/phonism_freeswitch_agent.py" 2>&1 | grep "HTTP/" | awk '{print $2}' )

    if [ $WGET_STATUS == "200" ]; then
        WGET_RUN=$(wget "${DOWNLOAD_HOST}/phonism_freeswitch_agent.py" -O "$DIR_INSTALL/phonism_freeswitch_agent.py" )
        msg_green "✔ Script downloaded to $DIR_INSTALL" && nl
    else
        msg_red "✘ Script could not be downloaded (Error $CURL_STATUS)." && nl && nl
        msg_red "Exiting, nothing has been installed." && nl
        cleanup_and_exit 1
    fi

fi

## Test run script

nl && msg_bold "Running script..." && nl

TEST_RUN_OUTPUT=$(${PATH_TO_PYTHON_ENV} "${DIR_INSTALL}/phonism_freeswitch_agent.py")
if [[ $? -eq 0 ]]; then
    msg_green "✔ Test Run successful" && nl
else 
    msg_red "✘ Script test run failed. Check output for details:" && nl && nl
    msg_bold "$TEST_RUN_OUTPUT" && nl && nl
    msg_red "Exiting, script has been installed but is not running." && nl
    cleanup_and_exit 1
fi


## Add cronjob

nl && msg_bold "Adding cronjob..." && nl

croncmd="${PATH_TO_PYTHON_ENV} ${DIR_INSTALL}/phonism_freeswitch_agent.py 2>&1 | /usr/bin/logger -t phonism_freeswitch_agent"
cronjob="* */1 * * * $croncmd"
( crontab -l | grep -v -F "$croncmd" ; echo "$cronjob" ) | crontab -

# Uninstalling the above cronjob is done using:
# ( crontab -l | grep -v -F "$croncmd" ) | crontab -


## Finish

nl && msg_green "Done!" && nl
cleanup_and_exit
