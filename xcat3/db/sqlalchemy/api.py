# -*- encoding: utf-8 -*-
#
# Copyright 2013 Hewlett-Packard Development Company, L.P.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""SQLAlchemy storage backend."""

import collections
import datetime
import threading

from oslo_db import exception as db_exc
from oslo_db.sqlalchemy import enginefacade
from oslo_db.sqlalchemy import utils as db_utils
from oslo_log import log
from oslo_utils import netutils
from oslo_utils import strutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
from sqlalchemy.orm.exc import NoResultFound, MultipleResultsFound
from sqlalchemy.orm import joinedload
from sqlalchemy import sql
from sqlalchemy import or_
from xcat3.common import exception
from xcat3.common.i18n import _, _LW
from xcat3.conf import CONF
from xcat3.db import api
from xcat3.db.sqlalchemy import models

LOG = log.getLogger(__name__)

_CONTEXT = threading.local()


def get_backend():
    """The backend is this module itself."""
    return Connection()


def _session_for_read():
    return enginefacade.reader.using(_CONTEXT)


def _session_for_write():
    return enginefacade.writer.using(_CONTEXT)


def model_query(model, *args, **kwargs):
    """Query helper for simpler session usage.

    :param session: if present, the session to use
    """

    with _session_for_read() as session:
        query = session.query(model, *args)
        return query


def add_identity_filter(query, value):
    """Adds an identity filter to a query.

    Filters results by ID, if supplied value is a valid integer.
    Otherwise attempts to filter results by UUID.

    :param query: Initial query to add filter to.
    :param value: Value for filtering results by.
    :return: Modified query.
    """
    if strutils.is_int_like(value):
        return query.filter_by(id=value)
    else:
        raise exception.InvalidIdentity(identity=value)


def add_nic_filter(query, value):
    """Adds a nic-specific filter to a query.

    Filters results by address, if supplied value is a valid MAC
    address. Otherwise attempts to filter results by identity.

    :param query: Initial query to add filter to.
    :param value: Value for filtering results by.
    :return: Modified query.
    """
    if netutils.is_valid_mac(value):
        return query.filter_by(address=value)
    else:
        return add_identity_filter(query, value)


def _paginate_query(model, limit=None, sort_key=None,
                    sort_dir=None, query=None):
    if not query:
        query = model_query(model)
    sort_keys = ['id']
    if sort_key and sort_key not in sort_keys:
        sort_keys.insert(0, sort_key)
    try:
        query = db_utils.paginate_query(query, model, limit, sort_keys,
                                        sort_dir=sort_dir)
    except db_exc.InvalidSortKey:
        raise exception.InvalidParameterValue(
            _('The sort_key value "%(key)s" is an invalid field for sorting')
            % {'key': sort_key})
    return query.all()


class Connection(api.Connection):
    """SqlAlchemy connection."""

    def __init__(self):
        pass

    def create_node(self, values):
        node = models.Node()
        node.update(values)
        nics_info = values.get('nics_info')

        with _session_for_write() as session:
            try:
                session.add(node)
                session.flush()
                if nics_info:
                    session.refresh(node)
                    for nic in nics_info['nics']:
                        nics = models.Nics()
                        nic['node_id'] = node.id
                        nic['uuid'] = uuidutils.generate_uuid()
                        nics.update(nic)
                        session.add(nics)
                        session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'mac' in exc.columns:
                    raise exc
                raise exception.DuplicateName(name=values['name'])
            return node

    def get_node_by_id(self, node_id):
        query = model_query(models.Node)
        query = query.filter_by(id=node_id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_id)

    def get_node_by_name(self, node_name):
        query = model_query(models.Node)
        query = query.filter_by(name=node_name)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NodeNotFound(node=node_name)

    def destroy_node(self, node_name):
        with _session_for_write():
            query = model_query(models.Node)
            query = query.filter_by(name=node_name)

            try:
                node = query.one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_name)
            nics_query = model_query(models.Nics)
            nics_query = nics_query.filter_by(node_id=node['id'])
            nics_query.delete()
            query.delete()

    def destroy_nodes(self, node_ids):
        with _session_for_write():
            query = model_query(models.Node).filter(
                models.Node.id.in_(node_ids))
            nodes = query.all()
            if not nodes:
                raise exception.NodeNotFound(node=node_ids)
            # delete the nics related to the nodes
            for node in nodes:
                nics_query = model_query(models.Nics)
                nics_query = nics_query.filter_by(node_id=node['id'])
                nics_query.delete()
            query.delete(synchronize_session=False)

    def get_nodeinfo_list(self, columns=None, filters=None, limit=None,
                          marker=None, sort_key=None, sort_dir=None):
        # list-ify columns default values because it is bad form
        # to include a mutable list in function definitions.
        if columns is None:
            columns = [models.Node.id]
        else:
            columns = [getattr(models.Node, c) for c in columns]

        query = model_query(*columns, base_model=models.Node)
        query = self._add_nodes_filters(query, filters)
        return _paginate_query(models.Node, limit, sort_key, sort_dir, query)

    def get_node_list(self, filters=None, limit=None, sort_key=None,
                      sort_dir=None):
        query = model_query(models.Node)
        return _paginate_query(models.Node, limit, sort_key, sort_dir, query)

    def get_node_in(self, node_names, filters=None):
        query = model_query(models.Node).filter(models.Node.name.in_(
            node_names))
        if 'reservation' in filters:
            query = query.filter_by(reservation=None)
        return query.all()

    def reserve_nodes(self, tag, node_names):
        with _session_for_write():
            query = model_query(models.Node).filter(
                models.Node.name.in_(node_names))
            count = query.filter_by(reservation=None).update(
                {'reservation': tag}, synchronize_session=False)

            nodes = query.all()
            if not nodes:
                raise exception.NodeNotFound(nodes=node_names)
            if count != len(node_names):
                raise exception.NodeLocked(nodes=node_names)
            return nodes

    def release_nodes(self, tag, node_names):
        with _session_for_write():
            query = model_query(models.Node).filter(
                models.Node.name.in_(node_names))
            count = query.filter_by(reservation=tag).update(
                {'reservation': None}, synchronize_session=False)

            if count != len(node_names):
                nodes = query.all()
                if not nodes:
                    raise exception.NodeNotFound(node_names)
                for node in nodes:
                    if node['reservation']:
                        raise exception.NodeLocked(node=node.name,
                                                   host=node['reservation'])

    def reserve_node(self, tag, node_id):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)
            count = query.filter_by(reservation=None).update(
                {'reservation': tag}, synchronize_session=False)
            try:
                node = query.one()
                if count != 1:
                    # Nothing updated and node exists. Must already be
                    # locked.
                    raise exception.NodeLocked(node=node.uuid,
                                               host=node['reservation'])
                return node
            except NoResultFound:
                raise exception.NodeNotFound(node_id)

    def release_node(self, tag, node_id):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)
            # be optimistic and assume we usually release a reservation
            count = query.filter_by(reservation=tag).update(
                {'reservation': None}, synchronize_session=False)
            try:
                if count != 1:
                    node = query.one()
                    if node['reservation'] is None:
                        raise exception.NodeNotLocked(node=node.uuid)
                    else:
                        raise exception.NodeLocked(node=node.uuid,
                                                   host=node['reservation'])
            except NoResultFound:
                raise exception.NodeNotFound(node_id)

    def create_nic(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()

        nics = models.Nics()
        nics.update(values)
        with _session_for_write() as session:
            try:
                session.add(nics)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'mac' in exc.columns:
                    raise exception.MACAlreadyExists(mac=values['mac'])
                raise exception.NicAlreadyExists(uuid=values['uuid'])
            return nics

    def get_nic_by_id(self, id):
        query = model_query(models.Nics).filter_by(id=id)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NicNotFound(nic=id)

    def get_nic_by_uuid(self, uuid):
        query = model_query(models.Nics).filter_by(uuid=uuid)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NicNotFound(nic=uuid)

    def get_nic_by_mac(self, mac):
        query = model_query(models.Nics).filter_by(mac=mac)
        try:
            return query.one()
        except NoResultFound:
            raise exception.NicNotFound(nic=mac)

    def get_nic_list(self, limit=None, sort_key=None, sort_dir=None):
        return _paginate_query(models.Nics, limit, sort_key, sort_dir)

    def get_nics_by_node_id(self, node_id, limit=None, sort_key=None,
                            sort_dir=None):
        query = model_query(models.Nics)
        query = query.filter_by(node_id=node_id)
        return _paginate_query(models.Nics, limit, sort_key, sort_dir, query)

    def create_nic(self, values):
        if not values.get('uuid'):
            values['uuid'] = uuidutils.generate_uuid()

        nic = models.Nics()
        nic.update(values)
        with _session_for_write() as session:
            try:
                session.add(nic)
                session.flush()
            except db_exc.DBDuplicateEntry as exc:
                if 'mac' in exc.columns:
                    raise exception.MACAlreadyExists(mac=values['mac'])
                raise exception.NicAlreadyExists(uuid=values['uuid'])
            return nic

    def update_nic(self, nic_id, values):
        # NOTE(dtantsur): this can lead to very strange errors
        if 'uuid' in values:
            msg = _("Cannot overwrite UUID for an existing Nics.")
            raise exception.InvalidParameterValue(err=msg)

        try:
            with _session_for_write() as session:
                query = model_query(models.Nics)
                query = add_nic_filter(query, nic_id)
                ref = query.one()
                ref.update(values)
                session.flush()
        except NoResultFound:
            raise exception.NicNotFound(nic=nic_id)
        except db_exc.DBDuplicateEntry:
            raise exception.MACAlreadyExists(mac=values['mac'])
        return ref

    def destroy_nic(self, nic_id):
        with _session_for_write():
            query = model_query(models.Nics)
            query = add_nic_filter(query, nic_id)
            count = query.delete()
            if count == 0:
                raise exception.NicNotFound(nic=nic_id)

    def get_conductors(self):
        interval = CONF.conductor.heartbeat_timeout
        limit = timeutils.utcnow() - datetime.timedelta(seconds=interval)
        return (model_query(models.Conductor).filter(
            models.Conductor.updated_at > limit).all())

    def register_conductor(self, values, update_existing=False):
        with _session_for_write() as session:
            query = (model_query(models.Conductor)
                     .filter_by(hostname=values['hostname']))
            try:
                ref = query.one()
                if ref.online is True and not update_existing:
                    raise exception.ConductorAlreadyRegistered(
                        conductor=values['hostname'])
            except NoResultFound:
                ref = models.Conductor()
                session.add(ref)
            ref.update(values)
            # always set online and updated_at fields when registering
            # a conductor, especially when updating an existing one
            ref.update({'updated_at': timeutils.utcnow(),
                        'online': True})
        return ref

    def get_conductor(self, hostname):
        try:
            return (model_query(models.Conductor)
                    .filter_by(hostname=hostname, online=True)
                    .one())
        except NoResultFound:
            raise exception.ConductorNotFound(conductor=hostname)

    def unregister_conductor(self, hostname):
        with _session_for_write():
            query = (model_query(models.Conductor)
                     .filter_by(hostname=hostname, online=True))
            count = query.update({'online': False})
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    def touch_conductor(self, hostname):
        with _session_for_write():
            query = (model_query(models.Conductor)
                     .filter_by(hostname=hostname))
            # since we're not changing any other field, manually set updated_at
            # and since we're heartbeating, make sure that online=True
            count = query.update({'updated_at': timeutils.utcnow(),
                                  'online': True})
            if count == 0:
                raise exception.ConductorNotFound(conductor=hostname)

    def update_node(self, node_id, values):
        try:
            return self._do_update_node(node_id, values)
        except db_exc.DBDuplicateEntry as e:
            if 'name' in e.columns:
                raise exception.DuplicateName(name=values['name'])
            else:
                raise

    def _do_update_node(self, node_id, values):
        with _session_for_write():
            query = model_query(models.Node)
            query = add_identity_filter(query, node_id)
            try:
                ref = query.with_lockmode('update').one()
            except NoResultFound:
                raise exception.NodeNotFound(node=node_id)

            ref.update(values)
        return ref
