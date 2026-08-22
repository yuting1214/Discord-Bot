#!/bin/bash
# Appends the preload list to the postgres command line, then hands over to
# Railway's wrapper unchanged.
#
# The preload list cannot be left to postgresql.conf: a command-line `-c`
# overrides the file, and the base image's CMD already passes some, so anything
# a deployer writes into postgresql.conf for shared_preload_libraries is
# silently ignored. Setting it here is the only place a deployer can influence
# it without rebuilding the image.
#
# Why not simply make CMD a shell command that expands the variable: the
# official docker-entrypoint.sh decides whether to run initdb by testing
# whether "$1" is `postgres`. Wrapping the command in `sh -c` makes "$1" `sh`,
# first-time initialisation never runs, and the database comes up empty.
set -e

PRELOAD="${SHARED_PRELOAD_LIBRARIES:-vchord_bm25}"

# Only when postgres is what is actually being started -- `docker run ... psql`
# and the major-upgrade job pass something else, and must not be given
# postgres' arguments.
if [ "$1" = "postgres" ]; then
    set -- "$@" -c "shared_preload_libraries=${PRELOAD}"
fi

exec /usr/local/bin/wrapper.sh "$@"
