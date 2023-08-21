#!/usr/bin/env bash

# Exit on error
set -o errexit

here=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

"$here/build_pg.sh"
"$here/build_server_base.sh"
"$here/build_server.sh"
"$here/build_dev_pod.sh"
