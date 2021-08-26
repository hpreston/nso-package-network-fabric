# -*- mode: python; python-indent: 4 -*-
import ncs
from .fabric_create import FabricServiceCallbacks
from .fabric_actions import FabricAction
from .tenant_create import TenantServiceCallbacks
from .tenant_actions import TenantAction


# ---------------------------------------------
# COMPONENT THREAD THAT WILL BE STARTED BY NCS.
# ---------------------------------------------
class Main(ncs.application.Application):
    def setup(self):
        # The application class sets up logging for us. It is accessible
        # through 'self.log' and is a ncs.log.Log instance.
        self.log.info('Main RUNNING')

        # Service callbacks require a registration for a 'service point',
        # as specified in the corresponding data model.
        
        # network-fabric
        self.register_service('network-fabric-servicepoint', FabricServiceCallbacks)
        self.register_action('network-fabric-full-test', FabricAction)

        # network-tenant
        self.register_service('network-tenant-servicepoint', TenantServiceCallbacks)
        self.register_action('network-tenant-full-test', TenantAction)


        # If we registered any callback(s) above, the Application class
        # took care of creating a daemon (related to the service/action point).

        # When this setup method is finished, all registrations are
        # considered done and the application is 'started'.

    def teardown(self):
        # When the application is finished (which would happen if NCS went
        # down, packages were reloaded or some error occurred) this teardown
        # method will be called.

        self.log.info('Main FINISHED')
