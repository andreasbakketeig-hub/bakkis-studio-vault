"""
Handoff: get an Ableton Live project ready to send to a collaborator.

Self-contained on purpose: this package uses only the Python standard library
and imports nothing else from Studio Vault, so it can become an app of its own.

    als.py         read a Live Set (.als) — never writes to it
    pluginlist.py  the receiver's one-click export of their installed plug-ins
"""
