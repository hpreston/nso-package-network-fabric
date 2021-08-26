# -*- mode: python; python-indent: 4 -*-
import ncs
from ncs.application import Service
import resource_manager.id_allocator as id_allocator
from .helper_functions import find_layer3_switch_pair


# ------------------------
# SERVICE CALLBACK EXAMPLE
# ------------------------
class FabricServiceCallbacks(Service):

    # The create() callback is invoked inside NCS FASTMAP and
    # must always exist.
    @Service.create
    def cb_create(self, tctx, root, service, proplist):
        self.log.info('Service create(service=', service._path, ')')

        vars = ncs.template.Variables()
        template = ncs.template.Template(service)
        # template.apply('network-fabric-template', vars)

        # Setup service wide resource pools 
        self.log.info(f"Creating id-pool VPC-DOMAIN-ID-POOL-{service.name} for fabric")
        template.apply("fabric-vpc-domain-id-pool")

        # Process switch-pair 
        for pair in service.switch_pair: 
            self.log.info(f"Calling create for switch-pair {pair.name}")
            self.switch_pair_create(tctx, root, service, pair)

        # Process switch 
        for switch in service.switch: 
            self.log.info(f"Calling create for switch {switch.device}")
            self.switch_create(root, service, switch)

        # Spanning-Tree Configuration for Fabric 
        self.log.info(f"Applying Spanning-Tree Root Bridge Configuration to Fabric {service}")
        self.fabric_spanning_tree_root(tctx, root, service)

        # Layer 3 switch-pair setup 
        layer3_pair = find_layer3_switch_pair(service)
        if layer3_pair: 
            self.log.info(f"Applying Layer 3 Base config onto layer3 pair [{layer3_pair.name}]")
            self.layer3_switch_pair_setup(tctx, root, layer3_pair, service)

        # Process fabric-interconnects 
        for fi in service.fabric_interconnect: 
            self.log.info(f"Calling create for fabric-interconnect {fi.device}")
            # NOTE: Currently there are no Fabric level configurations for a FI. Configuration is done during Segment Create

        # Process vcenter 
        for vcenter in service.vcenter: 
            self.log.info(f"Calling create for vcenter {vcenter.device}")
            # NOTE: Currently there are no Fabric level configurations for a vCenter. Configuration is done during Segment Create

    # Create and apply configurations for a switch-pair object in the fabric 
    def switch_pair_create(self, tctx, root, service, pair): 
        self.log.info(f"Processing switch-pair {pair.name}")

        # Basic switch setup steps 
        for switch in pair.switch: 
            # Configure Jumbo MTU
            self.jumbo_mtu_configure(root, service, switch)

            # Configure Spanning-Tree mode 
            self.spanning_tree_mode_apply(service, switch)

        # multiswitch-peerlink configuration 

        # Allocate VPC Domain ID 
        vpc_domain_id = self.allocate_vpc_domain_id(tctx, root, service, pair)

        if not vpc_domain_id: 
            self.log.info(f"VPC Domain ID Allocation not ready - {pair.name}")
        else: 
            self.log.info(f"VPC Domain ID Allocation is {pair.name}: {vpc_domain_id}")

            # Build Multiswitch Relationship 
            multiswitch = self.multiswitch_setup(tctx, root, service, pair, vpc_domain_id)

            # Process Fabric Trunks 
            for switch in pair.switch: 
                self.log.info(f"Setting up fabric-trunks on switch {switch.device}")
                for trunk in pair.fabric_trunk.port_channel: 
                    self.log.info(f"Calling create for trunk port-channel {trunk.name} [{trunk.description}]")
                    self.fabric_trunk_create(root, service, switch, trunk, vpc=True)



    def multiswitch_setup(self, tctx, root, service, pair, vpc_domain_id): 

        self.log.info(f"Setting Multiswitch relationship for {pair.name}")

        multiswitch_vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        # Gather common template variables for pair 
        # For consistency with other parts of YANG model, pair.multiswitch_peerlink.port_channel is 
        # a single item list.  There isn't a way to grab list item by index, and there is no way to 
        # know the name of the port-channel used. This simple loop grabs the portchannel as a variable
        for port_channel in pair.multiswitch_peerlink.port_channel: 
            multiswitch_portchannel = port_channel

        disable_trunk_negotiation = False
        multiswitch_vars.add("DISABLE_TRUNK_NEGOTIATION", disable_trunk_negotiation)
        multiswitch_vars.add("VPC_ENABLED", True)
        multiswitch_vars.add("VPC_DOMAIN_ID", vpc_domain_id)
        multiswitch_vars.add("VPC_PEERLINK_ID", multiswitch_portchannel.name)
        multiswitch_vars.add("LAYER3", pair.layer3)
        # VPC Peerlinks can't have explicit jumbo MTU set, switch will set itself
        multiswitch_vars.add("MTU_SIZE", "")


        for i, device in enumerate(pair.switch): 
            if i==0: 
                primary = root.devices.device[device.device]
                primary_ip_address = primary.config.interface.mgmt["0"].ip.address.ipaddr
            elif i==1: 
                secondary = root.devices.device[device.device]
                secondary_ip_address = secondary.config.interface.mgmt["0"].ip.address.ipaddr



        # Setup primary switch-pair member 
        self.log.info(f"Setting up primary multiswitch member: {primary.name} IP: {primary_ip_address}")

        multiswitch_vars.add("DEVICE_NAME", primary.name)
        multiswitch_vars.add("VPC_PEER_KEEPALIVE_SOURCE", primary_ip_address.split("/")[0])
        multiswitch_vars.add("VPC_PEER_KEEPALIVE_DESTINATION", secondary_ip_address.split("/")[0])

        self.log.info(f"multiswitch_vars: {multiswitch_vars}")
        template.apply("fabric-vpc-domain-base", multiswitch_vars)


        # Setup secondary switch-pair member
        self.log.info(f"Setting up secondary multiswitch member: {secondary.name} IP: {secondary_ip_address}")

        multiswitch_vars.add("DEVICE_NAME", secondary.name)
        multiswitch_vars.add("VPC_PEER_KEEPALIVE_SOURCE", secondary_ip_address.split("/")[0])
        multiswitch_vars.add("VPC_PEER_KEEPALIVE_DESTINATION", primary_ip_address.split("/")[0])

        self.log.info(f"multiswitch_vars: {multiswitch_vars}")
        template.apply("fabric-vpc-domain-base", multiswitch_vars)

        # Setup Multiswitch Peerlink Interfaces 
        for switch in pair.switch:
            # Setup variables for the 
            peerlink_vars = ncs.template.Variables()
            peerlink_vars.add("DEVICE_NAME", switch.device)
            peerlink_vars.add("DESCRIPTION", "VPC Peer Link")
            peerlink_vars.add("MODE", "trunk")
            peerlink_vars.add("VLAN_ID", "all")
            peerlink_vars.add("DISABLE_TRUNK_NEGOTIATION", disable_trunk_negotiation)
            # Note: IOS switches don't use an interface level MTU configuration so this value is ignored
            # VPC Peerlinks can't have explicit jumbo MTU set, switch will set itself
            peerlink_vars.add("MTU_SIZE", "")

            self.port_channel_member_setup(root, service, switch, port_channel, peerlink_vars, stp_guard_mode="")            



    def port_channel_member_setup(self, root, service, switch, port_channel, vars, stp_guard_mode=None): 

        self.log.info(f"Setting up member interfaces for port-channel {port_channel.name} on switch {switch.device}")

        template = ncs.template.Template(service)
        switch_platform = root.devices.device[switch.device].platform 

        vars.add("PORTCHANNEL_ID", port_channel.name)

        for case in port_channel.member_interface: 
            # Note: Reference that there is a "case" that is a "Case" object... this needs to be skipped as finding value in it is unclear 
            # if isinstance(trunk.member_interface[interface], ncs.maagic.Case): 

            # Logic to work out which YANG case representing an interface type is used for this trunk
            if isinstance(port_channel.member_interface[case], ncs.maagic.LeafList) and len(port_channel.member_interface[case]) > 0:
                self.log.info(f"port-channel {port_channel.name} uses member-interface type {case} with {len(port_channel.member_interface[case])} members")

                # Pull interface type out of case value (ie 'network-fabric:FortyGigabitEthernet') 
                member_interface_type = case.split(":")[1]

                # Loop over and process the individual interface members 
                for interface in port_channel.member_interface[case]: 
                    self.log.info(f"Processing member-interface {member_interface_type} {interface}")

                    vars.add("INTERFACE_ID", interface)
                    self.log.info("vars=", vars)

                    # Apply template for member interface based on Platform and Interface Type 
                    member_interface_template_name = "fabric-portchannel-member-interface-{platform}"
                    if switch_platform["name"] == "NX-OS" and member_interface_type == "Ethernet": 
                        member_interface_template_name = member_interface_template_name.format(platform="nxos")
                    elif switch_platform["name"] == "ios": 
                        member_interface_template_name = member_interface_template_name.format(platform=f"ios-{member_interface_type.lower()}")

                    # Spanning-Tree Guard Mode Configuration 
                    root_type, root_bridge, root_bridge_name = self.lookup_spanning_tree_root(service)

                    # See if an explicit stp_guard_mode provided
                    if stp_guard_mode is None: 
                        # See if the switch being configured is a root bridge for spanning-tree. if so set root guard
                        if ((root_type == "switch-pair" and switch.device in [switch.device for switch in root_bridge.switch]) 
                            or (root_type == "switch" and switch.device == root_bridge.device)): 

                            stp_guard_mode = "root"
                        
                        # else default to an empty string to NOT apply a guard mode 
                        else: 
                            stp_guard_mode = ""

                    vars.add("STP_GUARD_MODE", stp_guard_mode)



                    self.log.info(f"Applying interface template {member_interface_template_name}")
                    template.apply(member_interface_template_name, vars)



        return True

    # Resource Allocation for VPC Domain ID for Nexus VPC 
    def allocate_vpc_domain_id(self, tctx, root, service, pair): 

        self.log.info(f"Allocating VPC Domain Id for switch-pair {pair.name}")
        pool_name = "VPC-DOMAIN-ID-POOL-{}".format(service.name)
        alloc_name = "SWITCH-PAIR-{}".format(pair.name)
        id_allocator.id_request(
            service, 
            "/network-fabric[name='%s']" % (service.name),
            tctx.username,
            pool_name,
            alloc_name,
            False)
        vpc_domain_id = id_allocator.id_read(
            tctx.username,
            root,
            pool_name,
            alloc_name,
        )
        self.log.info("vpc_domain_id = {}".format(vpc_domain_id))
        return vpc_domain_id 


    # Apply MTU Configuration on switch 
    def jumbo_mtu_configure(self, root, service, switch):
        mtu_vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        switch_platform = root.devices.device[switch.device].platform 

        # Enable System Jumbo Frames
        # Catalyst Switches 3850 and 9300 max at 9198
        if switch_platform["name"] == "ios" and switch_platform["model"] in ["3850", "9300", "NETSIM"]:
            mtu_vars.add("FRAME_SIZE", "9198")
        else: 
            mtu_vars.add("FRAME_SIZE", "9216")

        mtu_vars.add("DEVICE_NAME", switch.device)
        self.log.info("Setting up Jumbo System MTU on switch {}".format(switch.device))
        self.log.info("mtu_vars=", mtu_vars)

        # Nexus switches have jumbomtu set to 9216 as default, setting it in NSO can cause compare-config failures 
        if switch_platform.name == "NX-OS": 
            self.log.info(f"Skipping explicit configuration of Jumbo System MTU on switch {switch.device} because {switch_platform.name} defaults to 9216.")
        # IOSv L2 switches in CML do not have the same system Jumbo configu for MTU that physical switches do
        elif switch_platform["model"] == "IOSv": 
            self.log.info(f"Skipping explicit configuration of Jumbo System MTU on switch {switch.device} because {switch_platform['model']} doesn't support system wide MTU setting.")
        else: 
            template.apply("fabric-system-jumbo-frames", mtu_vars)

    # Create and apply configurations for switch objects in the fabric
    def switch_create(self, root, service, switch):
        self.log.info(f"Processing switch {switch.device}")

        # Switch platform specific configuration values
        switch_platform = root.devices.device[switch.device].platform 
        self.log.info(f"Platform Name: {switch_platform.name} Version: {switch_platform.version} Model: {switch_platform.model}")

        # Configure Jumbo MTU
        self.jumbo_mtu_configure(root, service, switch)

        # TODO: If NX-OS switch need to enable feature lacp

        # Configure Spanning-Tree mode 
        self.spanning_tree_mode_apply(service, switch)

        # Process Fabric Trunks 
        for trunk in switch.fabric_trunk.port_channel: 
            self.log.info(f"Calling create for trunk port-channel {trunk.name} [{trunk.description}]")
            self.fabric_trunk_create(root, service, switch, trunk)

    # Function to create a Fabric Trunk Interface 
    def fabric_trunk_create(self, root, service, switch, trunk, vpc=""): 
        trunk_vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        # Switch platform specific configuration values
        switch_platform = root.devices.device[switch.device].platform 
        # self.log.info(f"Platform Name: {switch_platform.name} Version: {switch_platform.version} Model: {switch_platform.model}")

        # Older IOS Switches supported both ISL and DOT1Q trunk negotiation. This means it must be explicitly disabled on these platforms
        if switch_platform["model"] != "NETSIM" and switch_platform["name"] == "ios" and int(switch_platform["version"][0:2]) < 16: 
            disable_trunk_negotiation = True 
        else: 
            disable_trunk_negotiation = False

        self.log.info("Setting up fabric-trunk port-channel {} on switch {}".format(trunk.name, switch.device))
        trunk_vars.add("DEVICE_NAME", switch.device)
        trunk_vars.add("PORTCHANNEL_ID", trunk.name)
        trunk_description = "Interswitch Fabric Link"
        trunk_vars.add("DESCRIPTION", trunk.description)
        trunk_vars.add("VPC", vpc)
        trunk_vars.add("MODE", "trunk")
        trunk_vars.add("VLAN_ID", "all")
        trunk_vars.add("DISABLE_TRUNK_NEGOTIATION", disable_trunk_negotiation)
        # Note: IOS switches don't use an interface level MTU configuration so this value is ignored
        trunk_vars.add("MTU_SIZE", "9216")

        # Spanning-Tree Guard Mode Configuration 
        root_type, root_bridge, root_bridge_name = self.lookup_spanning_tree_root(service)
        stp_guard_mode = ""

        # See if the switch being configured is a root bridge for spanning-tree. if so set root guard
        if ((root_type == "switch-pair" and switch.device in [switch.device for switch in root_bridge.switch]) 
            or (root_type == "switch" and switch.device == root_bridge.device)): 

            stp_guard_mode = "root"

        trunk_vars.add("STP_GUARD_MODE", stp_guard_mode)

        self.log.info("trunk_vars=", trunk_vars)
        template.apply("fabric-portchannel-interface", trunk_vars)


        # self.log.info(f"choice_member_interface = {trunk.member_interface.choice_member_interface}")
        # self.log.info(f"choice_member_interface value = {type(trunk.member_interface.choice_member_interface._parent.get_value())}")

        # Setup member interfaces
        self.port_channel_member_setup(root, service, switch, trunk, trunk_vars)            


    # Functions to apply spanning-tree configuration to fabric 
    def spanning_tree_mode_apply(self, service, switch):
        """
        Configure the Spanning-Tree Mode on a switch.
        """

        switch_vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        # Configure Spanning-Tree Mode
        switch_vars.add("DEVICE_NAME", switch.device)

        self.log.info(f"Configuring Spanning-Tree Mode on switch {switch.device}")
        self.log.info(f"switch_vars={switch_vars}")
        template.apply("fabric-spanning-tree-mode", switch_vars)


    def fabric_spanning_tree_root(self, tctx, root, service): 
        """
        Configure Spanning-Tree Root Bridge appropriately on the network-fabric. 
        Focusing on: 
            - Root Bridge Identification and Configuration 
            - Root Guard protections configured across fabric 

        Possible enhancements for future: 
            - BPDU Guard for host ports (might be better in tenant/segment)
            - Spanning-Tree Port Type configurations (might be better in tenant/segment)
        """

        # Template objects
        stp_vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        # Basic Spanning-Tree Best practices 
        #   Spanning-Tree Version rpvst 

        # Determine Spanning-Tree Root for fabric
        root_type, root_bridge, root_bridge_name = self.lookup_spanning_tree_root(service)
        self.log.info(f"The {root_type} {root_bridge_name} was selected as root.")

        # Configure Spanning-Tree Priority on Root 
        if root_type == "switch-pair": 
            for switch in root_bridge.switch: 
                self.log.info(f"Configuring spanning-tree priority on switch {switch.device}.")
                stp_vars.add("DEVICE_NAME", switch.device)
                stp_vars.add("STP_PRIORITY", 4096)

                self.log.info(f"stp_vars={stp_vars}")
                template.apply("fabric-spanning-tree-priority", stp_vars)

    def lookup_spanning_tree_root(self, service): 
        """
        Lookup the spanning-tree root configured for a service. 

        Return tuple with (root_type, root_bridge, root_bridge_name)

        If no spanning-tree root is configured, return (None, None, None)
        """

        # Determine Spanning-Tree Root and Configure 
        root_type, root_bridge, root_bridge_name = None, None, None

        # Check if a spanning-tree root is configured
        for case in service.spanning_tree.root: 
            # Check for a configured value for each choice option
            if case == "network-fabric:switch-pair" and service.spanning_tree.root[case]: 
                # self.log.info(f"The switch-pair {service.spanning_tree.root[case]} was selected as root.")
                root_type = "switch-pair"
                root_bridge = service.switch_pair[service.spanning_tree.root[case]]
                root_bridge_name = root_bridge.name
            elif case == "network-fabric:switch" and service.spanning_tree.root[case]: 
                # self.log.info(f"The switch {service.spanning_tree.root[case]} was selected as root.")
                root_type = "switch"
                root_bridge = service.switch[service.spanning_tree.root[case]]
                root_bridge_name = root_bridge.device

        return (root_type, root_bridge, root_bridge_name)                

    def select_spanning_tree_root(self, service): 
        """
        # NOTE: The spanning-tree root has been make mandatory in YANG
        #       rather than allowing it to be determined. 
        #       Leaving this function in case it ever goes back to an 
        #       optional attribute.

        Pick the best spanning-tree root bridge from a fabric. 
        Selected root-bridge should be configured into the service persistently.

        Return tuple with (root_type, root_bridge, root_bridge_name)
        """

        root_type, root_bridge, root_bridge_name = None, None, None

        # Check if switch-pairs were configured in the fabric 
        if len(service.switch_pair) > 0: 
            self.log.info(f"fabric {service.name} has switch-pairs configured")
            root_type = "switch-pair" 
            for pair in service.switch_pair: 
                self.log.info(f"Pair {pair.name} has {len(pair.fabric_trunk.port_channel)} fabric-trunks")
                if root_bridge is None or len(pair.fabric_trunk.port_channel) > len(root_bridge.fabric_trunk.port_channel): 
                    root_bridge = pair
            
            root_bridge_name = root_bridge.name

            service.spanning_tree.root.switch_pair = root_bridge_name
        
        elif len(service.switch) > 0: 
            self.log.info(f"fabric {service.name} has switches configured")
            root_type = "switch" 
            for switch in service.switch: 
                self.log.info(f"Switch {switch.device} has {len(switch.fabric_trunk.port_channel)} fabric-trunks")
                if root_bridge is None or len(switch.fabric_trunk.port_channel) > len(root_bridge.fabric_trunk.port_channel): 
                    root_bridge = switch
            
            root_bridge_name = root_bridge.device

        return (root_type, root_bridge, root_bridge_name)

    # Apply the basic layer3 config onto the switches in a layer3 pair
    def layer3_switch_pair_setup(self, tctx, root, pair, service): 
        """
        Apply base Layer Config onto a Switch Pair's member switches.
        """

        vars = ncs.template.Variables()
        template = ncs.template.Template(service)

        for switch in pair.switch: 
            self.log.info(f"Setting up switch {switch.device} in {pair.name} for layer3.")
            vars.add("DEVICE_NAME", switch.device)
            self.log.info(f"vars={vars}")
            template.apply("fabric-layer3-setup", vars)



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

