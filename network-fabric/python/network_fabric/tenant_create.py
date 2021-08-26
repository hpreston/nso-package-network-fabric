# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service
import resource_manager.id_allocator as id_allocator
from .helper_functions import find_layer3_switch_pair


# ------------------------
# SERVICE CALLBACK EXAMPLE
# ------------------------
class TenantServiceCallbacks(Service):

    # The create() callback is invoked inside NCS FASTMAP and
    # must always exist.
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create(service=', service._path, ')')

        # For a tenant with layer3.enable = False no VRF configuration is done.
        if not service.layer3.enabled: 
            self.log.info(f"Network Tenant {service.name} has layer3 disabled. No VRF creation will be done.")
            return

        # VRF Creation: Lookup network-fabric resources
        self.log.info(f"Creating VRFs for {service.name} on network-fabric {service.fabric}.")

        # Find network-fabric and layer3 switch pair 
        fabric = root.network_fabric[service.fabric]
        # Lookup the Layer 3 Switch-Pair for the fabric on which VRFs will be created
        layer3_pair = find_layer3_switch_pair(fabric)

        # If a layer3_pair was NOT found, print error message and return function
        if not layer3_pair: 
            self.log.info(f"ERROR: network-fabric {fabric.name} does NOT have a layer3 enabled switch-pair. No VRFs can be configured.")
            raise(
                Exception(
                    f"\n  ERROR: network-fabric {fabric.name} does NOT have a layer3 enabled switch-pair. Either pick a fabric with a layer3 switch-pair, or disable layer3 for this tenant."
                    )
                )

        # Begin VRF Creation Process
        self.log.info(f"VRFs will be created on switch-pair {layer3_pair.name} on network-fabric {fabric.name} for this tenant.")
        for vrf in service.layer3.vrf: 
            self.log.info(f"Creating VRF {vrf}. (Note: Actual VRF name will be {service.name}_{vrf} on devices).")
            self.create_vrf(vrf, layer3_pair, service)

    # Apply the basic layer3 config onto the switches in a layer3 pair
    def create_vrf(self, vrf, layer3_pair, service): 
        """
        Create a VRF on each member of the Layer 3 Pair for a Fabric
        """

        # The name of a VRF will be the tenant_name-vrf_name to ensure uniqueness
        vrf_name = f"{service.name}_{vrf}"

        vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        for switch in layer3_pair.switch: 
            self.log.info(f"Setting up vrf {vrf_name} on switch {switch.device} in {layer3_pair.name}.")
            vars.add("DEVICE_NAME", switch.device)
            vars.add("VRFNAME", vrf_name)
            self.log.info(f"vars={vars}")
            template.apply("tenant-layer3-vrf-setup", vars)



    # The pre_modification() and post_modification() callbacks are optional,
    # and are invoked outside FASTMAP. pre_modification() is invoked before
    # create, update, or delete of the service, as indicated by the enum
    # ncs_service_operation op parameter. Conversely
    # post_modification() is invoked after create, update, or delete
    # of the service. These functions can be useful e.g. for
    # allocations that should be stored and existing also when the
    # service instance is removed.

    # @Service.pre_lock_create
    # def cb_pre_lock_create(self, tctx, root, service, proplist):
    #     self.log.info('Service plcreate(service=', service._path, ')')

    # @Service.pre_modification
    # def cb_pre_modification(self, tctx, op, kp, root, proplist):
    #     self.log.info('Service premod(service=', kp, ')')

    # @Service.post_modification
    # def cb_post_modification(self, tctx, op, kp, root, proplist):
    #     self.log.info('Service postmod(service=', kp, ')')

