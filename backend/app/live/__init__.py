"""Live rehearsal service: runs the existing pipeline script as a subprocess and streams progress events.

Nothing in here changes the frozen pipeline. A live run is always a REHEARSAL: the command line is fixed on the server, the client can send
no pipeline parameter, and held-out seeds (>= 900000) are never used.
"""
