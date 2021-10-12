# -*- coding: utf-8 -*-
"""
####################################################
###########         dependency          ############
####################################################
pip install DBUtils

# option 1: with postgres installed
# - mac: brew install postgresql
# - ubuntu: sudo apt install libpq-dev
pip install psycopg2

# option 2: with packaged binary
pip install psycopg2-binary

####################################################
###########         config.yml          ############
####################################################
pg:
  default:
    host: default-host
    port: 5432
    user: username
    password: password
    dbname: default_db_name
  some-other:
    host: some-other-host
    port: 5432
    user: username
    password: password
    dbname: default_db_name


####################################################
###########          usage              ############
####################################################
from spanner.pg import PG
with PG() as db:
    db.cursor.execute('select * from t_dummy_table')
    records = db.cursor.fetchall()

with PG('some-other', cursor_class='dict') as db:
    ...
"""
from . import config, logs

try:
    from dbutils.pooled_db import PooledDB
except ImportError:
    from DBUtils.PooledDB import PooledDB

import psycopg2 as client

LOGGER = logs.get_logger(__name__)


class PG(object):
    _POOLS = {}

    def __init__(self, profile='default') -> None:
        super().__init__()
        self.profile = profile
        self._ensure_pool()

    def _ensure_pool(self):
        if self.profile in PG._POOLS:
            return
        conf_profile = config.get(f"pg.{self.profile}", {})
        if len(conf_profile) == 0:
            raise ValueError(f'pg profile not configured: {self.profile}')
        conf = {
            'mincached': 1,
            'maxcached': 2,
            'maxshared': 2,
            'maxconnections': 20,
        }
        conf.update(conf_profile)
        LOGGER.debug(f"connecting [{self.profile}], host: {conf.get('host')}, db: {conf.get('db')}")

        pool = PooledDB(
            client,
            mincached=conf.pop('mincached', 1),
            maxcached=conf.pop('maxcached', 2),
            maxshared=conf.pop('maxshared', 2),
            maxconnections=conf.pop('maxconnections', 20),
            blocking=conf.pop('blocking', False),
            maxusage=conf.pop('maxusage', None),
            setsession=conf.pop('setsession', None),
            reset=conf.pop('reset', True),
            failures=conf.pop('failures', None),
            ping=conf.pop('ping', 1),
            **conf
        )
        PG._POOLS[self.profile] = pool

    def __enter__(self):
        self.conn = self.connect()
        self.cursor = self.conn.cursor()
        return self

    def connect(self):
        return self._POOLS.get(self.profile).connection()

    def __exit__(self, _type, _value, _trace):
        self.cursor.close()
        self.conn.close()