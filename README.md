# bonelab-mod-repo

The source code which powers https://blrepo.laund.moe

> **Warning**
> Please don't use this to host your own public repository, i don't want the community split and some people to recives fixes later.

## Running this

This project uses `poetry` to run, get it here: https://python-poetry.org/

To run, you need to copy `.env-example`, rename it to `.env` and add your mod.io oauth2 credentials: https://docs.mod.io/#authentication

- importer/json generator code: `poetry run start`.
- serve the content locally for testing: `poetry run python -m http.server -d ./static`
- continously generate the static content from the templates:  `poetry run staticjinja watch --outpath=./static`

## working principle

The importer python code writes mods from mod.io to a sqlite3 db at `./db.sqlite3`

It then runs error checks on the database, and finally generates the repository jsons from the database.

## todo

Todos are tracked through [issues](https://github.com/laundmo/bonelab-mod-repo/issues)
