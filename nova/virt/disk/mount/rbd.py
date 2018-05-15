# Copyright 2011 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Support for mounting images with rbd."""

import os
import time

from oslo_config import cfg
from oslo_log import log as logging

from nova.i18n import _, _LI, _LW
from nova import utils
from nova.virt.disk.mount import api

LOG = logging.getLogger(__name__)

rbd_opts = [
    cfg.IntOpt('timeout_rbd',
               default=10,
               help='Amount of time, in seconds, to wait for NBD '
               'device start up.'),
]

CONF = cfg.CONF
CONF.register_opts(rbd_opts)


class RbdMount(api.Mount):
    """ceph support disk images."""
    mode = 'rbd'

    def _inner_get_dev(self):
        LOG.debug('Get rbd device, %s', CONF.libvirt.rbd_map_type)
        if CONF.libvirt.rbd_map_type == "kernel":
            _out, err = utils.trycmd('rbd', '-p', self.image.pool,
                                     'map', self.image.name,
                                     discard_warnings=True, run_as_root=True)

            if err:
                self.error = _('rbd map error: %s') % err
                LOG.info(_LI('Rbd mount error: %s'), self.error)
                return False

            _out = _out.split('\n')[0]
            device = _out.split('/')[2]
            devicedir = "/sys/block/%s" % device
            for _i in range(CONF.timeout_rbd):
                if os.path.exists(devicedir):
                    self.device = _out
                    break
                time.sleep(1)
            else:
                self.error = _('Device %s map failed,dir not exist') % _out
                LOG.info(_LI('RBD mount error: %s'), self.error)

                # Cleanup
                _outu, err = utils.trycmd('rbd', 'umap',
                                          _out, run_as_root=True)
                if err:
                    LOG.warning(_LW('Detaching from erroneous rbd device'
                                    'returned error: %s'), self.error)
                return False

        elif CONF.libvirt.rbd_map_type == "nbd":
            _out, err = utils.trycmd('rbd', '-p', self.image.pool,
                                     'nbd', 'map', self.image.name,
                                     discard_warnings=True, run_as_root=True)
            if err:
                self.error = _('rbd map error: %s') % err
                LOG.info(_LI('Rbd mount error: %s'), self.error)
                return False

            _out = _out.split('\n')[0]
            device = _out.split('/')[2]
            pidfile = "/sys/block/%s/pid" % device
            for _i in range(CONF.timeout_rbd):
                if os.path.exists(pidfile):
                    self.device = _out
                    break
                time.sleep(1)
            else:
                self.error = _('rbd device %s did not show up') % _out
                LOG.info(_LI('RBD mount error: %s'), self.error)

                # Cleanup
                _outu, err = utils.trycmd('rbd', 'nbd', 'umap', _out,
                                          run_as_root=True)
                if err:
                    LOG.warning(_LW('Detaching from erroneous rbd device'
                                    'returned  error: %s'), self.error)
                return False

        self.error = ''
        self.linked = True
        return True

    def get_dev(self):
        """Retry requests for Rbd devices."""
        return self._get_dev_retry_helper()

    def unget_dev(self):
        if not self.linked:
            LOG.debug('Release rbd is not needed.')
            return
        LOG.debug('Release rbd device %s', self.device)

        if CONF.libvirt.rbd_map_type == "kernel":
            utils.execute('rbd', 'unmap', self.device, run_as_root=True)
        elif CONF.libvirt.rbd_map_type == "nbd":
            utils.execute('rbd', 'nbd', 'unmap', self.device, run_as_root=True)
        self.linked = False
        self.device = None

    def flush_dev(self):
        """flush NBD block device buffer."""
        # Perform an explicit BLKFLSBUF to support older qemu-nbd(s).
        # Without this flush, when a nbd device gets re-used the
        # qemu-nbd intermittently hangs.
        if self.device:
            utils.execute('blockdev', '--flushbufs',
                          self.device, run_as_root=True)
