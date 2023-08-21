#!/usr/bin/env bash

# Install PostGIS
psql --username vagrant -c "CREATE EXTENSION postgis" vagrant_dev
