#!/bin/bash

SRC="$HOME/data/tickets"
DEST="$HOME/data/backups"

mkdir -p "$DEST"
tar -czf "$DEST/tickets_$(date +%F).tar.gz" "$SRC"
