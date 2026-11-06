#!/bin/sh

set -e  # Exit on any error

echo ""
echo "------------------------------------------"
echo "🚀 Starting container with ROLE=\"$ROLE\""
echo "------------------------------------------"

case "$ROLE" in
  flask)
    echo "🟢 Starting Flask API (Server)..."
    exec venv/bin/python3.11 -m bootstrap.flask_app
    ;;
    
  celery)
    # threads: safe only when all adapters are remote (stateless HTTP, I/O-bound).
    # solo:    single-process, single-thread — required for local adapters.
    #          Avoids CUDA context conflicts and loads the model only once.
    #          No parallelism, but safe and memory-efficient for local inference.
    # CELERY_POOL can always be overridden explicitly by the operator.
    if [ "${USE_REMOTE_DOCLING:-false}" = "true" ] && [ "${USE_REMOTE_EMBEDDING:-false}" = "true" ]; then
      CELERY_POOL="${CELERY_POOL:-threads}"
    else
      CELERY_POOL="${CELERY_POOL:-solo}"
    fi
    echo "🔧 Starting Celery worker: concurrency=$CELERY_WORKER, pool=$CELERY_POOL, queues=$CELERY_QUEUES"
    # -n NAME@%h: a name without "@" is read by Celery as the host part, so every pod got the node name
    # celery@data_sources and the same exclusive pidbox queue; two pods alive together (a rolling update) collided
    # with ResourceLocked (fork/ROADMAP.md R-537). %h is the pod hostname, expanded by Celery.
    exec venv/bin/celery -A infrastructure.celery.app worker -c $CELERY_WORKER --pool=$CELERY_POOL --loglevel=info -Q $CELERY_QUEUES -n data_sources@%h
    ;;

  debug)
    echo "🐞 Debug mode activated — container will stay alive."
    tail -f /dev/null
    ;;

  *)
    echo "❌ ERROR: Unknown ROLE \"$ROLE\""
    echo "Valid roles are: flask, celery, debug"
    exit 1
    ;;
esac
