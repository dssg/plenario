# Plenar.io

RESTful API for geospatial and time aggregation across multiple open datasets.

This project is funded by the [NSF Computer and Information Science and Engineering (CISE) Directorate](http://www.nsf.gov/dir/index.jsp?org=CISE) through a grant to the [Urban Center for Computation and Data](https://urbanccd.org/) (UrbanCCD) at the [Computation Institute](http://ci.uchicago.edu) of the [University of Chicago](http://uchicago.edu) and [Argonne National Laboratory](http://www.anl.gov). It is being implemented by [DataMade](http://datamade.us) and UrbanCCD.

For more details, see the presentation slides from [Exploring Open Civic Data Through Time and Space](https://docs.google.com/presentation/d/1Une-A1k0mUAIYac5UlmeSDLw4VyHYsaw1NW5f4YKWas/edit#slide=id.p) given in June 2014.

## Running locally

* Get the Plenario source:

``` bash
git clone git@github.com:UrbanCCD-UChicago/plenario.git
```

Install support libraries for Python:

``` bash
cd plenario
pip install -r requirements.txt
```

Create a PostgreSQL database for Plenario. (If you aren't
  already running [PostgreSQL](http://www.postgresql.org/), we recommend
  installing version 9.3 or later.)

```
createdb plenario_dev
```

Make sure your local database has the [PostGIS](http://postgis.net/) extension:

```
psql plenario_dev
plenario_test=# CREATE EXTENSION postgis;
```

Create your own `settings.py` file:

```
cp plenario/settings.py.example plenario/settings.py
```

You will want to change, at the minimum, the following `settings.py` fields:

* `DATABASE_CONN`: edit this field to reflect your PostgreSQL
  username, server hostname, port, and database name. 

* `DEFAULT_USER`: change the username, email and password on the administrator account you will use on Plenario locally.

If you want your datasets hosted on an S3 bucket, edit the fields
`AWS_ACCESS_KEY`, `AWS_SECRET_KEY`, and `S3_BUCKET`. Otherwise,
datasets will be downloaded locally to the directory in the `DATA_DIR`
field.

Additionally, create your own `celery_settings.py` file:

```
cp plenario/celery_settings.py.example plenario/celery_settings.py
```

You probably do not need to change any values in `celery_settings.py`,
unless you are running redis remotely (see `BROKER_URL`).

Before running the server, [Redis](http://redis.io/) and
[Celery](http://www.celeryproject.org/) also need to be running.

* To start Redis locally (in the background):
```
redis-server &
```

* To start Celery locally (in the background):
```
celery -A plenario.celery_app worker --loglevel=info &
```

Initialize the plenario database by running `python init_db.py`. 

Finally, run the server:

```
python runserver.py
```

Once the server is running, navigate to http://localhost:5001/ . From
the homepage, click 'Login' to log in with the username and password
from `settings.py`. Once logged in, go to 'Add a dataset' under the
'Admin' menu to add your own datasets.

## Running with Docker
Additionally, we support installing Plenario using Docker containers. Because of the variety of PostgreSQL/Docker configuration options, there are two containers needed for Plenario. One is a Plenario web server Docker container, which we provide a Dockerfile for. The other is a PostgreSQL+PostGIS database Docker container. We recommend using [helmi03/docker-postgis](https://github.com/helmi03/docker-postgis). Please read carefully about persisting data to the database. 

1. Boot a PostGIS/PostgreSQL setup. See above. 
2. Alter settings in settings.py.docker. 
3. Run `docker build .`
4. Run `docker run`
5. Congrats! Plenario should now be running in the container. 

# Data

New datasets are actively being added to the Plenario API. We keep track of them in this [Google Doc](https://docs.google.com/spreadsheet/ccc?key=0Au-2OHnpwhGTdGJzUWJ2SERwVXZLeDU4Y3laWFJvNEE&usp=sharing#gid=0).

# Dependencies
We used the following open source tools:

* [PostgreSQL](http://www.postgresql.org/) - database version 9.3 or greater
* [PostGIS](http://postgis.net/) - spatial database for PostgreSQL
* [Flask](http://flask.pocoo.org/) - a microframework for Python web applications
* [SQL Alchemy](http://www.sqlalchemy.org/) - Python SQL toolkit and Object Relational Mapper
* [Green Unicorn](http://gunicorn.org/) - Python WSGI HTTP Server for UNIX
* [psycopg2](http://initd.org/psycopg/) - PostgreSQL adapter for the Python 
* [GeoAlchemy 2](http://geoalchemy-2.readthedocs.org/en/0.2.4/) - provides extensions to SQLAlchemy for working with spatial databases
* [Celery](http://www.celeryproject.org/) - asynchronous task queue
* [Redis](http://redis.io/) - key-value cache


## Team

### UrbanCCD
* Charlie Catlett
* Brett Goldstein
* Svetlozar Nestorov
* Jonathan Giuffrida
* Maggie King
* Jiajun Shen

### DataMade
* Derek Eder
* Eric van Zanten
* Forest Gregg
* Michael Castelle

## Join Our Community

Join our community to hear about platform updates, new features and discuss the potential uses of Plenario. We want to start a conversation with you, the users, about what Plenario can do for you - whether you're a city manager, an app developer, a researcher, or a citizen interested in exploring open data.

[Join our Google Group](https://groups.google.com/forum/#!forum/plenariodataportal)

## Errors / Bugs

If something is not behaving intuitively, it is a bug, and should be reported.
Report it here: https://github.com/UrbanCCD-UChicago/plenario/issues

## Note on Patches/Pull Requests
 
* Fork the project.
* Make your feature addition or bug fix.
* Send us a pull request. Bonus points for topic branches.

## Copyright

Copyright (c) 2014 University of Chicago and DataMade. Released under the [MIT License](https://github.com/UrbanCCD-UChicago/plenario/blob/master/LICENSE).
