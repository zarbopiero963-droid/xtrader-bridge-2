#!/usr/bin/env python3
"""
BetRelay
Telegram → CSV → XTrader

Entrypoint: la logica vive nel package `xtrader_bridge`.
"""

from xtrader_bridge.app import App

if __name__ == "__main__":
    App().mainloop()
