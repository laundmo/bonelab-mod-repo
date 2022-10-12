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

for development i recommend passing `onepage=True` to `    await downloader_main()` in `__main__.py`- this will limit the amount of mods fetched from mod.io to a single page (100 mods).

## working principle

The importer python code writes mods from mod.io to a sqlite3 db at `./db.sqlite3`

It then runs error checks on the database, and finally generates the repository jsons from the database.

## todo

Todos are tracked through [issues](https://github.com/laundmo/bonelab-mod-repo/issues)

## contributing

Before starting to work on code, please comment on the respective issue or open a new one to let others know that its being worked on. You don't have to wait for a response - it's just for others to see which issues are taken.
