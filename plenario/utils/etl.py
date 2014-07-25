import requests
import re
import os
from datetime import datetime, date, time
from plenario.database import task_session as session, task_engine as engine, \
    Base
from plenario.models import MetaTable, MasterTable
from urlparse import urlparse
from csvkit.unicsv import UnicodeCSVReader
from csvkit.typeinference import normalize_table
import gzip
from sqlalchemy import Boolean, Float, DateTime, Date, Time, String, Column, \
    Integer, Table, text, func, select, or_, and_
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.exc import NoSuchTableError
from types import NoneType

DATA_DIR = os.environ['WOPR_DATA_DIR']

COL_TYPES = {
    bool: Boolean,
    int: Integer,
    float: Float, 
    datetime: TIMESTAMP, 
    date: Date,
    time: Time,
    NoneType: String,
    unicode: String
}

class PlenarioETL(object):
    
    def __init__(self, meta, data_dir=DATA_DIR):
        for k,v in meta.items():
            setattr(self, k, v)
        domain = urlparse(self.source_url).netloc
        fourbyfour = self.source_url.split('/')[-1]
        self.view_url = 'http://%s/api/views/%s' % (domain, fourbyfour)
        self.dl_url = '%s/rows.csv?accessType=DOWNLOAD' % self.view_url
        self.data_dir = data_dir
    
    def add(self, fpath=None):
        if fpath:
            self.fpath = fpath
        else:
            self._download_csv()
        self._get_or_create_data_table()
        self._insert_raw_data()
        self._dedupe_raw_data()
        self._make_src_table()
        self._find_new_records()
        self._update_dat_table()
        self._update_master()
        self._cleanup_temp_tables()
    
    def update(self, fpath=None):
        self._get_or_create_data_table()
        if fpath:
            self.fpath = fpath
        else:
            self._download_csv()
        self._insert_raw_data()
        self._dedupe_raw_data()
        self._make_src_table()
        new = self._find_new_records()
        if new:
            self._update_dat_table()
            self._update_master()
            changes = self._find_changes()
            if changes:
                self._update_dat_current_flag()
                self._update_master_current_flag()
        self._cleanup_temp_tables(changes=changes)

    def _download_csv(self):
        r = requests.get(self.dl_url, stream=True)
        self.fpath = '%s/%s_%s.csv.gz' % (self.data_dir, 
              self.dataset_name, datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))
        with gzip.open(self.fpath, 'wb') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)
                    f.flush()
 
    def _cleanup_temp_tables(self, changes=False):
        self.raw_table.drop(bind=engine, checkfirst=True)
        self.dedupe_table.drop(bind=engine, checkfirst=True)
        self.src_table.drop(bind=engine, checkfirst=True)
        self.new_table.drop(bind=engine, checkfirst=True)
        if changes:
            self.chg_table.drop(bind=engine, checkfirst=True)


    def _get_or_create_data_table(self):
        # Step One: Make a table where the data will eventually live
        try:
            self.dat_table = Table('dat_%s' % self.dataset_name, Base.metadata, 
                autoload=True, autoload_with=engine, extend_existing=True)
        except NoSuchTableError:
            has_nulls = {}
            with gzip.open(self.fpath, 'rb') as f:
                reader = UnicodeCSVReader(f)
                header = reader.next()
                col_types,col_vals = normalize_table(reader)
                for idx, col in enumerate(col_vals):
                    if None in col_vals:
                        has_nulls[header[idx]] = True
                    else:
                        has_nulls[header[idx]] = False
            cols = [
                Column('start_date', TIMESTAMP, server_default=text('CURRENT_TIMESTAMP')),
                Column('end_date', TIMESTAMP, server_default=text('NULL')),
                Column('current_flag', Boolean, server_default=text('TRUE')),
                Column('dataset_row_id', Integer, primary_key=True),
            ]
            for col_name,d_type in zip(header, col_types):
                kwargs = {}
                if has_nulls[col_name]:
                    kwargs['nullable'] = True
                cols.append(Column(slugify(col_name), COL_TYPES[d_type], **kwargs))
            self.dat_table = Table('dat_%s' % self.dataset_name, Base.metadata, 
                          *cols, extend_existing=True)
            self.dat_table.create(engine, checkfirst=True)

    def _insert_raw_data(self):
        # Step Two: Insert data directly from CSV
        cols = []
        skip_cols = ['start_date', 'end_date', 'current_flag', 'dataset_row_id']
        for col in self.dat_table.columns:
            kwargs = {}
            if col.name not in skip_cols:
                cols.append(Column(col.name, col.type, **kwargs))
        self.raw_table = Table('raw_%s' % meta['dataset_name'], Base.metadata, 
                          *cols, extend_existing=True)
        self.raw_table.drop(bind=engine, checkfirst=True)
        self.raw_table.append_column(Column('dup_row_id', Integer, primary_key=True))
        self.raw_table.create(bind=engine, checkfirst=True)
        names = [c.name for c in self.dat_table.columns]
        copy_st = 'COPY raw_%s (' % self.dataset_name
        for idx, name in enumerate(names):
            if name not in skip_cols:
                if idx < len(names) - 1:
                    copy_st += '%s, ' % name
                else:
                    copy_st += '%s)' % name
        else:
            copy_st += "FROM STDIN WITH (FORMAT CSV, HEADER TRUE, DELIMITER ',')"
        conn = engine.raw_connection()
        cursor = conn.cursor()
        with gzip.open(self.fpath, 'rb') as f:
            cursor.copy_expert(copy_st, f)
        conn.commit()

    def _dedupe_raw_data(self):
        # Step Three: Make sure to remove duplicates based upon what the user 
        # said was the business key
        self.dedupe_table = Table('dedupe_%s' % self.dataset_name, Base.metadata,
                            Column('dup_row_id', Integer, primary_key=True), 
                            extend_existing=True)
        self.dedupe_table.drop(bind=engine, checkfirst=True)
        self.dedupe_table.create(bind=engine)
        bk = slugify(self.business_key)
        ins = self.dedupe_table.insert()\
            .from_select(
                ['dup_row_id'],
                select([func.max(self.raw_table.c.dup_row_id)])\
                .group_by(getattr(self.raw_table.c, bk))
            )
        conn = engine.connect()
        conn.execute(ins)

    def _make_src_table(self):
        # Step Four: Make a table with every unique record.
        cols = []
        skip_cols = ['start_date', 'end_date', 'current_flag']
        for col in self.dat_table.columns:
            if col.name not in skip_cols:
                kwargs = {}
                if col.primary_key:
                    kwargs['primary_key'] = True
                if col.server_default:
                    kwargs['server_default'] = col.server_default
                cols.append(Column(col.name, col.type, **kwargs))
        self.src_table = Table('src_%s' % self.dataset_name, Base.metadata, 
                          *cols, extend_existing=True)
        self.src_table.drop(bind=engine, checkfirst=True)
        self.src_table.create(bind=engine)
        ins = self.src_table.insert()\
            .from_select(
                [c for c in src_table.columns.keys() if c != 'dataset_row_id'],
                select([c for c in self.raw_table.columns if c.name != 'dup_row_id'])\
                    .where(self.raw_table.c.dup_row_id == self.dedupe_table.c.dup_row_id)
            )
        conn = engine.connect()
        conn.execute(ins)

    def _find_new_records(self):
        # Step Five: Find the new records
        bk = slugify(self.business_key)
        self.new_table = Table('new_%s' % self.dataset_name, Base.metadata,
                          Column('id', Integer, primary_key=True),
                          extend_existing=True)
        self.new_table.drop(bind=engine, checkfirst=True)
        self.new_table.create(bind=engine)
        ins = self.new_table.insert()\
            .from_select(
                ['id'],
                select([self.src_table.c.dataset_row_id])\
                    .select_from(self.src_table.join(self.dat_table, 
                        getattr(self.src_table.c, bk) == \
                            getattr(self.dat_table.c, bk), isouter=True))\
                    .where(self.dat_table.c.dataset_row_id == None)
            )
        conn = engine.connect()
        try:
            conn.execute(ins)
            return True
        except TypeError:
            # No new records
            return False

    def _update_dat_table(self):
        # Step Six: Update the dat table
        skip_cols = ['end_date', 'current_flag']
        dat_cols = [c for c in self.dat_table.columns.keys() if c not in skip_cols]
        src_cols = [text("'%s' AS start_date" % datetime.now().isoformat())]
        src_cols.extend([c for c in self.src_table.columns if c.name not in skip_cols])
        ins = self.dat_table.insert()\
            .from_select(
                dat_cols,
                select(src_cols)\
                    .select_from(self.src_table.join(self.new_table,
                        self.src_table.c.dataset_row_id == self.new_table.c.id))
            )
        conn = engine.connect()
        conn.execute(ins)

    def _update_master(self):
        # Step Seven: Insert new records into master table
        dat_cols = [
            self.dat_table.c.start_date,
            self.dat_table.c.end_date,
            self.dat_table.c.current_flag,
        ]
        dat_cols.append(getattr(self.dat_table.c, slugify(self.location))\
            .label('location'))
        dat_cols.append(getattr(self.dat_table.c, slugify(self.latitude))\
            .label('latitude'))
        dat_cols.append(getattr(self.dat_table.c, slugify(self.longitude))\
            .label('longitude'))
        dat_cols.append(getattr(self.dat_table.c, slugify(observed_date))\
            .label('obs_date'))
        dat_cols.append(text("NULL AS obs_ts"))
        dat_cols.append(text("NULL AS geotag1"))
        dat_cols.append(text("NULL AS geotag2"))
        dat_cols.append(text("NULL AS geotag3"))
        dat_cols.append(text("'%s' AS dataset_name" % self.dataset_name))
        dat_cols.append(self.dat_table.c.dataset_row_id)
        dat_cols.append(text(
            "ST_PointFromText('POINT(' || dat_%s.%s || ' ' || dat_%s.%s || ')', 4326) \
                  as location_geom" % (
                      self.dataset_name, self.longitude, 
                      self.dataset_name, self.latitude,
                  )))
        mt = MasterTable.__table__
        ins = mt.insert()\
            .from_select(
                [c for c in mt.columns.keys() if c != 'master_row_id'],
                select(dat_cols)\
                    .select_from(self.dat_table.join(self.new_table, 
                        self.dat_table.c.dataset_row_id == self.new_table.c.id)
                    )
            )
        conn = engine.connect()
        conn.execute(ins)

    def _find_changes(self):
        # Step Eight: Find changes
        self.chg_table = Table('chg_%s' % self.dataset_name, Base.metadata,
                      Column('id', Integer, primary_key=True), 
                      extend_existing=True)
        self.chg_table.drop(bind=engine, checkfirst=True)
        self.chg_table.create(bind=engine)
        bk = slugify(self.business_key)
        skip_cols = ['start_date', 'end_date', 'current_flag', bk]
        src_cols = [c for c in self.src_table.columns if c.name != bk]
        dat_cols = [c for c in self.dat_table.columns if c.name not in skip_cols]
        and_args = []
        for s,d in zip(src_cols, dat_cols):
            ors = or_(s != None, d != None)
            ands = and_(ors, s != d)
            and_args.append(ands)
        ins = self.chg_table.insert()\
            .from_select(
                ['id'],
                select([self.src_table.c.dataset_row_id])\
                    .select_from(self.src_table.join(self.dat_table,
                        getattr(self.src_table.c, bk) == \
                        getattr(self.dat_table.c, bk)))\
                    .where(or_(*and_args))
                    .where(and_(self.dat_table.c.current_flag == True, 
                        or_(getattr(self.src_table.c, bk) != None, 
                            getattr(self.dat_table.c, bk) != None)))
            )
        conn = engine.connect()
        try:
            conn.execute(ins)
            return True
        except TypeError:
            # No changes found
            return False

    def _update_dat_current_flag(self):
        # Step Nine: Update data table with changed records

        # Need to figure out how to make the end_date more granular than a day. 
        # For datasets that update more frequently than every day, this will be
        # crucial so that we are updating the current_flag on the correct records.
        update = self.dat_table.update()\
            .values(current_flag=False, end_date=datetime.now().strftime('%Y-%m-%d'))\
            .where(self.dat_table.c.dataset_row_id == self.chg_table.c.id)\
            .where(self.dat_table.c.current_flag == True)
        conn = engine.connect()
        conn.execute(update)
        return None

    def update_master_current_flag(self):
        # Step Ten: Update master table with changed records

        # Need to figure out how to make the end_date more granular than a day. 
        # For datasets that update more frequently than every day, this will be
        # crucial so that we are updating the current_flag on the correct records.
        update = MasterTable.update()\
            .value(current_flag=False, end_date=datetime.now().isoformat())\
            .where(MasterTable.dataset_row_id == self.dat_table.c.dataset_row_id)\
            .where(self.dat_table.c.current_flag == False)\
            .where(self.dat_table.c.end_date == datetime.now().strftime('%Y-%m-%d'))
        return None
