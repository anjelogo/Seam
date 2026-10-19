from procrastinate import App, PsycopgConnector
from seam_shared import db

app = App(connector=PsycopgConnector(conninfo=db.url()), import_paths=["app.worker.tasks"])
