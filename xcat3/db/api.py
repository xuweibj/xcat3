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
"""
Base classes for storage engines
"""

import abc

from oslo_config import cfg
from oslo_db import api as db_api
import six

_BACKEND_MAPPING = {'sqlalchemy': 'xcat3.db.sqlalchemy.api'}
IMPL = db_api.DBAPI.from_config(cfg.CONF, backend_mapping=_BACKEND_MAPPING,
                                lazy=True)


def get_instance():
    """Return a DB API instance."""
    return IMPL


@six.add_metaclass(abc.ABCMeta)
class Connection(object):
    """Base class for storage system connections."""

    @abc.abstractmethod
    def __init__(self):
        """Constructor."""

    @abc.abstractmethod
    def get_nodeinfo_list(self, columns=None, filters=None, limit=None,
                          sort_key=None, sort_dir=None):
        """Get specific columns for matching nodes.

        Return a list of the specified columns for all nodes that match the
        specified filters.

        :param columns: List of column names to return.
                        Defaults to 'id' column when columns == None.
        :param filters: Filters to apply. Defaults to None.
                        :reserved: True | False
                        :reserved_by_any_of: [conductor1, conductor2]
                        :provision_state: provision state of node
                        :provisioned_before:
                            nodes with provision_updated_at field before this
                            interval in seconds
        :param limit: Maximum number of nodes to return.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        :returns: A list of tuples of the specified columns.
        """

    @abc.abstractmethod
    def get_node_list(self, filters=None, limit=None, marker=None,
                      sort_key=None, sort_dir=None):
        """Return a list of nodes.

        :param filters: Filters to apply. Defaults to None.

                        :associated: True | False
                        :reserved: True | False
                        :provision_state: provision state of node
                        :provisioned_before:
                            nodes with provision_updated_at field before this
                            interval in seconds
        :param limit: Maximum number of nodes to return.
        :param sort_key: Attribute by which results should be sorted.
        :param sort_dir: direction in which results should be sorted.
                         (asc, desc)
        """

    @abc.abstractmethod
    def get_node_in(self, names, filters=None):
        """ Get nodes collection within names

        :param names: the nodes names to select
        :param filters: Filters to apply. Defaults to None.
        :return: a list of nodes
        """

    @abc.abstractmethod
    def reserve_node(self, tag, node_id):
        """Reserve a node.

        To prevent other ManagerServices from manipulating the given
        Node while a Task is performed, mark it reserved by this host.

        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id.
        :returns: A Node object.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is already reserved.
        """

    @abc.abstractmethod
    def release_node(self, tag, node_id):
        """Release the reservation on a node.

        :param tag: A string uniquely identifying the reservation holder.
        :param node_id: A node id.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is reserved by another host.
        :raises: NodeNotLocked if the node was found to not have a
                 reservation at all.
        """

    @abc.abstractmethod
    def reserve_nodes(self, tag, node_names):
        """Reserve nodes.

        :param tag: A string uniquely identifying the reservation holder.
        :param node_names: The name of nodes.
        :return object of nodes
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is already reserved.
        """

    @abc.abstractmethod
    def release_nodes(self, tag, node_names):
        """Release the reservation on nodes

        :param tag: A string uniquely identifying the reservation holder.
        :param node_names: The name of nodes.
        :raises: NodeNotFound if the node is not found.
        :raises: NodeLocked if the node is reserved by another host.
        :raises: NodeNotLocked if the node was found to not have a
                 reservation at all.
        """

    @abc.abstractmethod
    def create_node(self, values):
        """Create a new node.

        :param values: A dict containing several items used to identify
                       and track the node. For example:

                       ::

                        {
                         'name": 'test_node'
                         'mgt': 'ipmi',
                         'control_info': {'ipmi_address':'10.0.0.1',
                                          'ipmi_user': 'admin'}
                        }
        :returns: A node.
        """

    @abc.abstractmethod
    def get_node_by_id(self, node_id):
        """Return a node.

        :param node_id: The id of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def destroy_node(self, node_name):
        """Destroy a node and its associated resources.

        :param node_id: The name of a node.
        """

    @abc.abstractmethod
    def destroy_nodes(self, node_ids):
        """Destroy nodes and its associated resources.

        :param node_ids: The ids of nodes.
        """

    @abc.abstractmethod
    def get_node_by_name(self, node_name):
        """Return a node.

        :param node_name: The name of a node.
        :returns: A node.
        """

    @abc.abstractmethod
    def create_nic(self, values):
        """Create a port
        :param values: A dict containing several items used to identify
                       and track the nic. For example:

                       ::

                        {
                         'ip": '13.0.0.1'
                         'mac': '43:87:0a:05:65:01',
                         'primary': 'true'
                        }
        :returns: A nic.
        """

    @abc.abstractmethod
    def get_nic_by_id(self, id):
        """Get nic from id"""

    @abc.abstractmethod
    def get_nic_by_uuid(self, uuid):
        """Get nic from uuid"""

    @abc.abstractmethod
    def get_nic_by_mac(self, mac):
        """Get nic from mac"""

    @abc.abstractmethod
    def get_nic_list(self, limit=None, sort_key=None, sort_dir=None):
        """List all the nics"""

    @abc.abstractmethod
    def get_nics_by_node_id(self, node_id, limit=None, sort_key=None,
                            sort_dir=None):
        """List nics owned by the specific node"""

    @abc.abstractmethod
    def create_nic(self, values):
        """Create nic"""

    @abc.abstractmethod
    def update_nic(self, nic_id, values):
        """update nic"""

    @abc.abstractmethod
    def destroy_nic(self, nic_id):
        """destroy nic"""

    @abc.abstractmethod
    def get_conductors(self):
        """Return conductor nodes

        :returns: Conductor nodes
        """
