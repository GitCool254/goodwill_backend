#!/bin/bash

TICKETS_DIR="$HOME/goodwill_backend/data/tickets"
DAYS=14

find "$TICKETS_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +$DAYS -exec rm -rf {} \;
