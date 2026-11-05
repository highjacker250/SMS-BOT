#!/bin/bash

echo "Installing Playwright Browsers..."
playwright install chromium
playwright install-deps

echo "Starting Bot..."
python main.py
