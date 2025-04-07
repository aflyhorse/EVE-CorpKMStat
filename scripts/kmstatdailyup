#!/bin/bash

# Change to the directory where you cloned the repository
cd /root/EVE-CorpKMStat
# Activate your virtualenv
source .direnv/python-3.9.2/bin/activate

# Run the script
flask parseall >> instance/update-$(date --iso-8601).log