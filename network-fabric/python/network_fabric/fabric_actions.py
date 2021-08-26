import ncs
from ncs.dp import Action
from _ncs import decrypt
from _ncs.dp import action_set_timeout
import genie.testbed

class FabricAction(Action): 
    @Action.action
    def cb_action(self, uinfo, name, kp, action_input, action_output, trans):
        self.log.info('FabricAction: ', name)
        test_container = ncs.maagic.get_node(trans, kp)
        service = test_container._parent
        root = ncs.maagic.get_root(trans)
        trans.maapi.install_crypto_keys()

        if name == 'fabric':
            # This test can run longer than the default. Increasing timeout to 6 minutes
            action_set_timeout(uinfo, 360)

            self.fabric_test(service, root, action_input, action_output)

    def fabric_test(self, service, root, action_input, action_output): 
        self.log.info(f'Running fabric_test on network-fabric {service.name}')

        # Setup
        # - Create testbed(s) object 
        #   - switch-pairs 
        #   - switches
        # - Connect to devices/testbeds 

        switchpair_testbed, switch_testbed = self.create_fabric_testbeds(service, root)

        # Connect to all devices in the testbeds
        for testbed in [switchpair_testbed, switch_testbed]:
            self.testbed_connect(testbed)
            # self.testbed_connection_status(testbed)

            # NOTE: Should any test/validation/error message be logged if a device can't be connected to?



        # Test VPC Domain for switchpairs 
        for pair in service.switch_pair: 
            vpc_domain_test = self.test_vpc_domain(pair, switchpair_testbed, action_output)

        # Test Fabric Trunks 
        # - Test port-channel interface is up 
        # - Test all member-interfaces are up 
        # - TODO: Test CDP neighbors on member interfaces match configured peer 

        for pair in service.switch_pair: 
            for switch in pair.switch: 
                trunk_test = self.fabric_trunk_test(switch.device, pair.fabric_trunk, switchpair_testbed, action_output, 
                                                    ignore_trunks=[ str(trunk.name) for trunk in pair.multiswitch_peerlink.port_channel])

        # TODO: Test this with a fabric that has a switch included (not just switch-pairs)
        for switch in service.switch: 
            trunk_test = self.fabric_trunk_test(switch.device, switch.fabric_trunk, switch_testbed, action_output)

        # Run Spanning-Tree Test
        self.spanning_tree_test(service, root, switchpair_testbed, switch_testbed, action_input, action_output)

        # Be sure to cleanup connections to devices
        for testbed in [switchpair_testbed, switch_testbed]:
            self.testbed_disconnect(testbed)
            # self.testbed_connection_status(testbed)

        # if len(output["error"]) == 0: 
        if len(action_output.error) == 0: 
            action_output.message = "Fabric test was successful"
            action_output.success = True
        else: 
            action_output.message = "Errors were encountered during test."
            action_output.success = False

    def spanning_tree_test(self, service, root, switchpair_testbed, switch_testbed, action_input, action_output):

        self.log.info(f"Testing Spanning-Tree State for network-fabric {service.name}")

        results = {
            "success": True, 
            "details": [], 
            "error": []
        }

        # Lookup Spanning-Tree Root details from service
        root_type, root_bridge, root_bridge_name = self.lookup_spanning_tree_root(service)
        self.log.info(f"Spanning-Tree root is {root_bridge_name}")

        spanning_tree_details = {}

        for testbed in [switchpair_testbed, switch_testbed]: 
            # self.log.info(f"Running testbed {testbed.name}. {testbed.devices}")
            for device in testbed.devices: 
                spanning_tree_details[device] = testbed.devices[device].parse("show spanning-tree detail")

                # - Verify all switches running rapid-pvst 
                stp_proto_msg = self.spanning_tree_protocol_test(device, spanning_tree_details[device], action_output)
                if stp_proto_msg: 
                    results["error"].append(stp_proto_msg)

                # - Verify configured spanning-tree root is root on all switches
                stp_root_msg = self.spanning_tree_root_test(device, spanning_tree_details[device], root_bridge_name, action_output)
                if stp_root_msg: 
                    results["error"].append(stp_root_msg)


        # For debugging print spanning-tree-details
        # self.log.info(spanning_tree_details)

        if len(results["error"]) > 0: 
            results["success"] = False

        self.log.info(f"results: {results}")

        return results

    def spanning_tree_root_test(self, device, spanning_tree_details, root_bridge_name, action_output): 

        msgs = []

        self.log.info(f"Running Spanning-Tree Root Test on device {device}")

        for protocol, stp_details in spanning_tree_details.items():
            self.log.info(f"Checking Spanning-Tree Protocol {protocol} for root per vlan.")
            for vlan_id, vlan_details in stp_details["vlans"].items(): 
                self.log.info(f"Checking VLAN ID {vlan_id}.")
                # self.log.info(vlan_details)

                if root_bridge_name in device and "root_of_the_spanning_tree" not in vlan_details.keys(): 
                    self.log.info(f"Device {device} is NOT the Spanning-Tree root for VLAN {vlan_id} but should be.")
                    msgs.append(f"Device {device} is NOT the Spanning-Tree root for VLAN {vlan_id} but should be.")
                elif (root_bridge_name not in device and "root_of_the_spanning_tree" in vlan_details.keys()) and vlan_details["root_of_the_spanning_tree"]: 
                    self.log.info(f"Device {device} is the Spanning-Tree root for VLAN {vlan_id} but should NOT be.")
                    msgs.append(f"Device {device} is the Spanning-Tree root for VLAN {vlan_id} but should NOT be.")

        if len(msgs) == 0: 
            msgs = None
        else: 
            for msg in msgs: 
                test_error = action_output.error.create()
                test_error.test = "spanning-tree root bridge"
                test_error.message = msg 
                
        return msgs


    def spanning_tree_protocol_test(self, device, spanning_tree_details, action_output, spanning_tree_protocol="rapid_pvst"): 

        # self.log.info(f"Device {device} is running {spanning_tree_details.keys()}")
        msg = None

        if "rapid_pvst" not in spanning_tree_details.keys(): 
            msg = f'device {device} is running Spanning-Tree Protocol {", ".join(spanning_tree_details.keys())}. It should be "rapid-pvst"'
            test_error = action_output.error.create()
            test_error.test = "spanning-tree protocol version"
            test_error.message = msg 

        return msg

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

    def fabric_trunk_test(self, switch, fabric_trunks, testbed, action_output, ignore_trunks=[]): 

        results = {
            "success": True, 
            "details": [], 
            "error": []
        }

        show_portchannel_summary = None

        self.log.info(f"Testing fabric trunk status on switch {switch}")
        self.log.info(f"The following port-channel ids will be ignored during testing: {', '.join(ignore_trunks)}")

        if testbed.devices[switch].os == "nxos": 
            show_portchannel_summary = testbed.devices[switch].parse("show port-channel summary")

        elif testbed.devices[switch].os in ["ios", "iosxe"]: 
            show_portchannel_summary = testbed.devices[switch].parse("show etherchannel summary")
        
        # for debug, print parsed data
        self.log.info(f"show_portchannel_summary={show_portchannel_summary}")

        # TODO: The logic needs to be validated for IOS/IOSXE devices and data model as well as NXOS

        # Tests: 
        # Match the fabric-trunks configured on service are the only port-channels configured
        set_ignore_trunks = set(ignore_trunks)
        set_fabric_trunks = set([ trunk.name for trunk in fabric_trunks.port_channel])
        set_port_channels = set([ str(trunk_details["bundle_id"]) for trunk_name, trunk_details in show_portchannel_summary["interfaces"].items() ])

        # for debug, print parsed data
        # self.log.info(f"set_fabric_trunks={set_fabric_trunks}")
        # self.log.info(f"set_port_channels={set_port_channels}")

        # Make sure all fabric trunks are configured as port-channels 
        missing_fabric_trunks = set_fabric_trunks.difference(set_port_channels).difference(set_ignore_trunks)
        if missing_fabric_trunks != set(): 
            msg = f'switch {switch} is missing port-channels for fabric-trunks [{", ".join(missing_fabric_trunks)}]'
            results["error"].append(msg)
            test_error = action_output.error.create()
            test_error.test = "fabric trunk exist"
            test_error.message = msg 

        # Make sure there are no EXTRA port-channels configured 
        extra_port_channels = set_port_channels.difference(set_fabric_trunks).difference(set_ignore_trunks)
        if extra_port_channels != set(): 
            msg = f'switch {switch} has extra port-channels [{", ".join(extra_port_channels)}]'
            results["error"].append(msg)
            test_error = action_output.error.create()
            test_error.test = "fabric trunk exist"
            test_error.message = msg 

        # Make sure member interfaces from fabric-trunks match configured port-channel members and are up
        for trunk in fabric_trunks.port_channel: 
            self.log.info(f'Checking fabric-trunk port-channel{trunk.name} member-interfaces on switch {switch}.')

            for case in trunk.member_interface: 
                # Skip the "choice" case and find the actual case with members
                if case != "network-fabric:member-interface" and len(trunk.member_interface[case]) > 0: 
                    member_interface_type = trunk.member_interface[case]
                    member_interfaces = [ f'{member_interface_type}{interface}' for interface in trunk.member_interface[case] ]
            
            self.log.info(f'Configured member interfaces on trunk are {member_interface_type} {member_interfaces}')

            # Get the operational port-channel data 
            try: 
                operational_port_channel = show_portchannel_summary["interfaces"][f'Port-channel{trunk.name}']
                # self.log.info(f'operational_port_channel={operational_port_channel}')
            except KeyError: 
                msg = f'Port-channel{trunk.name} is not operational on switch {switch}'
                results["error"].append(msg)
                test_error = action_output.error.create()
                test_error.test = "fabric member test"
                test_error.message = msg 
                break

            # See if member interfaces match (set math)
            set_member_interfaces = set(member_interfaces)
            set_operational_members = set(operational_port_channel["members"].keys())
            if set_member_interfaces != set_operational_members: 
                msg = f'Port-channel{trunk.name} on switch {switch} member interfaces incorrect. Should be [{", ".join(set_member_interfaces)}] but is [{", ".join(set_operational_members)}]'
                results["error"].append(msg)
                test_error = action_output.error.create()
                test_error.test = "fabric member test"
                test_error.message = msg 

            # debug and dev 
            # self.log.info(f"set_member_interfaces={set_member_interfaces}")
            # self.log.info(f"set_operational_members={set_operational_members}")

            # Verify that all operational member interfaces are up
            for interface_name, details in operational_port_channel["members"].items(): 
                if details["flags"] != "P": 
                    msg = f'Port-channel{trunk.name} on switch {switch} member interface {interface_name} is not up. Currently has flag {details["flags"]}'
                    results["error"].append(msg)
                    test_error = action_output.error.create()
                    test_error.test = "fabric member test"
                    test_error.message = msg 


        if len(results["error"]) > 0: 
            results["success"] = False

        self.log.info(f"results: {results}")

        return results


    def test_vpc_domain(self, pair, testbed, action_output): 

        results = {
            "success": True, 
            "details": [], 
            "error": []
        }

        # Test VPC Domain 
        # - CDP neighbors on member interfaces see peer interfaces
        # - Test that all VPCs are "up"

        self.log.info(f'Testing VPC Domain on switch-pair {pair.name}')

        # dictionaries to hold parser output
        show_vpc = {}
        show_portchannel_summary = {}

        for switch in pair.switch: 
            # Parse "show vpc" for switch 
            self.log.info(f'Gathering show vpc details from {switch.device}')
            # Parser Docs: https://pubhub.devnetcloud.com/media/genie-feature-browser/docs/#/parsers/show%2520vpc
            show_vpc[switch.device] = testbed.devices[switch.device].parse("show vpc")
        
        # self.log.info(f"show_vpc: {show_vpc}")

        # Basic State Verifications
        self.log.info(f'Testing Basic State Verifications on {pair.name}')
        for switch in pair.switch: 
            # - Keepalive up 
            self.log.info(f'Checking keepalive status on {switch.device}')
            try: 
                if show_vpc[switch.device]["vpc_peer_keepalive_status"] != "peer is alive": 
                    msg = f'switch-pair {pair.name}, switch {switch.device}, vpc keepalive down'
                    results["error"].append(msg)
                    test_error = action_output.error.create()
                    test_error.test = "vpc keepalive test"
                    test_error.message = msg
            except KeyError: 
                msg = f'switch-pair {pair.name}, switch {switch.device}, no vpc operational status discovered'
                results["error"].append(msg)
                test_error = action_output.error.create()
                test_error.test = "vpc keepalive test"
                test_error.message = msg


            # - Peerlink up 
            self.log.info(f'Checking peerlink status on {switch.device}')
            try: 
                if show_vpc[switch.device]["vpc_peer_status"] != "peer adjacency formed ok": 
                    results["error"].append(f'switch-pair {pair.name}, switch {switch.device},  {show_vpc[switch.device]["vpc_peer_status"]}')
                    test_error = action_output.error.create()
                    test_error.test = "vpc peerlink test"
                    test_error.message = f'switch-pair {pair.name}, switch {switch.device},  {show_vpc[switch.device]["vpc_peer_status"]}'
            except KeyError: 
                msg = f'switch-pair {pair.name}, switch {switch.device}, no vpc operational status discovered'
                results["error"].append(msg)
                test_error = action_output.error.create()
                test_error.test = "vpc peerlink test"
                test_error.message = msg

            # - Both member interfaces in peer-link port-channel are up 
            self.log.info(f'Checking peerlink member status on {switch.device}')
            try: 
                peerlink_portchannel_data = show_vpc[switch.device]['peer_link']
                for peerlink_portchannel in peerlink_portchannel_data.values(): 
                    self.log.info(f'Peer Link ID is {peerlink_portchannel["peer_link_id"]}, Peer Link Interface {peerlink_portchannel["peer_link_ifindex"]}, Peer Link Port State, {peerlink_portchannel["peer_link_port_state"]}')
                    # Parser docs: https://pubhub.devnetcloud.com/media/genie-feature-browser/docs/#/parsers/show%2520port-channel%2520summary
                    show_portchannel_summary[switch.device] = testbed.devices[switch.device].parse("show port-channel summary")

                    peerlink_details = show_portchannel_summary[switch.device]["interfaces"][f'Port-channel{peerlink_portchannel["peer_link_id"]}']
                    for member, details in peerlink_details["members"].items(): 
                        if details["flags"] != "P": 
                            msg = f'switch-pair {pair.name}, switch {switch.device}, peer-link member interface {member} status {details["flags"]}'
                            results["error"].append(msg)
                            test_error = action_output.error.create()
                            test_error.test = "vpc peerlink member test"
                            test_error.message = msg 

            except KeyError: 
                msg = f'switch-pair {pair.name}, switch {switch.device}, no vpc operational status discovered'
                results["error"].append(msg)
                test_error = action_output.error.create()
                test_error.test = "vpc peerlink member test"
                test_error.message = msg

            # self.log.info(f'show_portchannel_summary: {show_portchannel_summary}')

            # - Test that all VPCs are "up"            
            self.log.info(f'Checking VPC operational status on {switch.device}')
            try: 
                if show_vpc[switch.device]["num_of_vpcs"] > 0: 
                    vpc_interface_data = show_vpc[switch.device]['vpc']
                    for vpc_id, details in vpc_interface_data.items(): 
                        self.log.info(f'VPC ID {vpc_id}, Port-channel Interface {details["vpc_ifindex"]}, Port State, {details["vpc_port_state"]}')
                        if details["vpc_port_state"] != "up": 
                            msg = f'switch-pair {pair.name}, switch {switch.device}, vpc {vpc_id} for Port-channel {details["vpc_ifindex"]} is {details["vpc_port_state"]}'
                            results["error"].append(msg)
                            test_error = action_output.error.create()
                            test_error.test = "vpc status test"
                            test_error.message = msg
                else: 
                    self.log.info(f'Device {switch.device} has no VPCs configured.')
            except KeyError: 
                msg = f'switch-pair {pair.name}, switch {switch.device}, no vpc operational status discovered'
                results["error"].append(msg)
                test_error = action_output.error.create()
                test_error.test = "vpc peerlink member test"
                test_error.message = msg

            # Verifications related to intent from service model 
            #   - interface relationships on peerlink 
            #   - check that configured "fabric trunks" id numbers match the configured VPCs (ie nothing missing or extra)
            #   - Check that peerlink ID and interfaces match the configured model 

        if len(results["error"]) > 0: 
            results["success"] = False

        self.log.info(f"results: {results}")

        return results

    # TODO: Refactor to use the create_testbed and create_pyats_device from helper_functions
    def create_fabric_testbeds(self, service, root):

        self.log.info('Setting up testbed for switch-pairs.')
        switchpair_testbed_data = {
            "testbed": {
                "name": f"fabric-{service.name}-switchpairs", 
            }, 
            "devices": {}
            }
        for pair in service.switch_pair: 
            self.log.info(f'Setting up testbed for switch-pair {pair.name}.')
            for switch in pair.switch: 
                switchpair_testbed_data["devices"].update(self.create_pyats_device(root, switch.device))

        # NOTE: Uncomment this line just for dev and debugging. Will print credentials in clear text
        # self.log.info(f"switchpair_testbed_data: {switchpair_testbed_data}")

        switchpair_testbed = genie.testbed.load(switchpair_testbed_data)

        switch_testbed = None
        self.log.info('Setting up testbed for switches.')

        switch_testbed_data = {
            "testbed": {
                "name": f"fabric-{service.name}-switches", 
            }, 
            "devices": {}
            }
        for switch in service.switch: 
            switch_testbed_data["devices"].update(self.create_pyats_device(root, switch.device))

        # NOTE: Uncomment this line just for dev and debugging. Will print credentials in clear text
        # self.log.info(f"switch_testbed_data: {switch_testbed_data}")

        switch_testbed = genie.testbed.load(switch_testbed_data)

        return (switchpair_testbed, switch_testbed)




    def create_pyats_device(self, root, device_name): 
        self.log.info(f'Creating pyATS device definition for device {device_name}')

        device = root.devices.device[device_name]
        auth = root.devices.authgroups.group[device.authgroup].default_map

        # Keys are NSO Platform Names and Values are pyATS OS options
        device_os_map = {
            "ios": "ios", 
            "ios-xe": "iosxe", 
            "NX-OS": "nxos", 
            "ios-xr": "iosxr", 
            "asa": "asa"
        }

        # Default ports for CLI protocols
        connection_port_map = { 
            "ssh": 22, 
            "telnet": 23
        }

        # Determine the protocol and port for the testbed 
        protocol = str(device.device_type.cli.protocol)
        port = device.port if device.port else connection_port_map[protocol] 

        device_data = {
            device_name: {
                "os": device_os_map[device.platform.name], 
                "connections": {
                    "default": {
                        "ip": device.address, 
                        "protocol": protocol, 
                        "port": port,
                    },
                },
                "credentials": {
                    "default": {
                        "username": auth.remote_name, 
                        "password": decrypt(auth.remote_password), 
                    }
                }
            }
        }

        return device_data


    # TODO: Refactor to use versions from helper_functions
    def testbed_connect(self, testbed): 
        # Only if a valid testbed was created
        if testbed: 
            self.log.info(f"Connecting testbed {testbed.name}")
            testbed.connect(learn_hostname=True, log_stdout=False)

    def testbed_connection_status(self, testbed): 
        # Only if a valid testbed was created
        if testbed: 
            # Print connection status
            for device in testbed.devices: 
                self.log.info(f"Connection status {device}: {testbed.devices[device].connected}")


    def testbed_disconnect(self, testbed): 
        # Only if a valid testbed was created
        if testbed: 
            self.log.info(f"Disconnecting testbed {testbed.name}")
            for device in testbed.devices: 
                self.log.info(f"Disconnecting device {device}")
                testbed.devices[device].settings.GRACEFUL_DISCONNECT_WAIT_SEC = 0
                testbed.devices[device].settings.POST_DISCONNECT_WAIT_SEC = 0
                testbed.devices[device].disconnect()
